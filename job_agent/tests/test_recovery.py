import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from job_agent.http import Client, AccessBlocked, RateLimited
from job_agent.__main__ import collect
from job_agent.parse import parse_job
from job_agent.store import Store

SAMPLE = Path(__file__).resolve().parent / 'fixtures/sample-job.html'


def response(status, headers=None, body=b'<p>ok</p>'):
    r = Mock(status_code=status, headers=headers or {'Content-Type': 'text/html'}, encoding='utf-8')
    r.iter_content.return_value = [body]
    return r


class RecoveryTests(unittest.TestCase):
    def test_blocked_empty_run_does_not_create_spreadsheets(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(keywords='data science', location='Pakistan', max_jobs=100,
                hours=2400, export_dir=Path(tmp) / 'exports')
            client = Mock()
            client.get.side_effect = AccessBlocked('blocked')
            with Store(Path(tmp) / 'db') as store, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(collect(args, store, client), 2)
            self.assertTrue((args.export_dir / 'run-report.json').exists())
            self.assertFalse((args.export_dir / 'jobs.csv').exists())
            self.assertFalse((args.export_dir / 'contacts.csv').exists())
            self.assertFalse((args.export_dir / 'jobs.json').exists())

    def test_existing_jobs_export_survives_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(keywords='Python', location='Pakistan', max_jobs=1,
                hours=168, export_dir=Path(tmp) / 'exports')
            client = Mock()
            client.get.side_effect = AccessBlocked('blocked')
            with Store(Path(tmp) / 'db') as store, contextlib.redirect_stdout(io.StringIO()):
                store.save(parse_job(SAMPLE.read_text(), 'https://www.linkedin.com/jobs/view/999999999'))
                self.assertEqual(collect(args, store, client), 2)
            self.assertEqual(len(json.loads((args.export_dir / 'jobs.json').read_text())), 1)

    def test_legacy_cooldown_is_respected_for_different_search(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / 'search-a.http-state.json'
            old.write_text(json.dumps({'www.linkedin.com': time.time() + 900}))
            client = Client(delay=0, state_path=Path(tmp) / 'http-state.json', legacy_state_paths=[old])
            with patch.object(client.session, 'get') as get:
                with self.assertRaises(AccessBlocked):
                    client.get('https://www.linkedin.com/jobs-guest/search?keywords=different')
                get.assert_not_called()

    def test_deferred_run_has_retry_time_and_report(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(keywords='Python', location='Pakistan', max_jobs=1,
                hours=168, enrichment_limit=0, phone_region='PK', export_dir=Path(tmp) / 'exports')
            client = Mock()
            client.get.side_effect = RateLimited('https://www.linkedin.com', time.time() + 3600)
            with Store(Path(tmp) / 'db') as store, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(collect(args, store, client), 3)
            report = json.loads((Path(tmp) / 'exports/run-report.json').read_text())
            self.assertEqual(report['status'], 'rate_limited')
            self.assertGreater(report['retry_after_seconds'], 3500)
            self.assertEqual(report['saved'], 0)

    def test_short_retry_after_waits_and_recovers(self):
        client = Client(delay=0)
        with patch('job_agent.http.validate_url'), patch('job_agent.http.time.sleep') as sleep, patch.object(
            client.session, 'get', side_effect=[response(429, {'Retry-After': '2'}), response(200)]) as get:
            self.assertEqual(client.get('https://www.linkedin.com/jobs/test')[0], '<p>ok</p>')
            self.assertEqual(get.call_count, 2)
            self.assertTrue(any(call.args[0] >= 2 for call in sleep.call_args_list))

    def test_long_cooldown_persists_across_clients(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'cooldown.json'
            client = Client(delay=0, state_path=state)
            with patch('job_agent.http.validate_url'), patch.object(client.session, 'get', return_value=response(429, {'Retry-After': '3600'})) as get:
                with self.assertRaises(AccessBlocked) as error:
                    client.get('https://www.linkedin.com/jobs/test')
                self.assertTrue(hasattr(error.exception, 'retry_at'))
                self.assertEqual(get.call_count, 1)
            restarted = Client(delay=0, state_path=state)
            with patch.object(restarted.session, 'get') as get:
                with self.assertRaises(AccessBlocked):
                    restarted.get('https://www.linkedin.com/jobs/test')
                get.assert_not_called()
            with patch('job_agent.http.validate_url'), patch.object(restarted.session, 'get', return_value=response(200)):
                self.assertEqual(restarted.get('https://example.com/jobs')[0], '<p>ok</p>')

    def test_http_date_retry_after_is_not_ignored(self):
        client = Client(delay=0)
        with patch('job_agent.http.validate_url'), patch.object(client.session, 'get', return_value=response(429, {'Retry-After': 'Wed, 21 Oct 2099 07:28:00 GMT'})) as get:
            with self.assertRaises(AccessBlocked) as error:
                client.get('https://www.linkedin.com/jobs/test')
            self.assertGreater(error.exception.retry_at, 4_000_000_000)
            self.assertEqual(get.call_count, 1)

    def test_retry_budget_is_bounded(self):
        client = Client(delay=0)
        with patch('job_agent.http.validate_url'), patch('job_agent.http.time.sleep'), patch.object(
            client.session, 'get', return_value=response(429, {'Retry-After': '1'})) as get:
            with self.assertRaises(AccessBlocked):
                client.get('https://www.linkedin.com/jobs/test')
            self.assertEqual(get.call_count, 3)

    def test_resume_skips_stored_details_and_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(keywords='Python', location='Pakistan', max_jobs=1,
                hours=168, enrichment_limit=0, phone_region='PK', export_dir=Path(tmp) / 'exports', resume=True)
            client = Mock()
            client.get.side_effect = [('<a href="https://www.linkedin.com/jobs/view/999999999">A</a>', 'https://www.linkedin.com'), ('', 'https://www.linkedin.com')]
            with Store(Path(tmp) / 'db') as store, contextlib.redirect_stdout(io.StringIO()):
                store.save(parse_job(SAMPLE.read_text(), 'https://www.linkedin.com/jobs/view/999999999'))
                self.assertEqual(collect(args, store, client), 0)
                self.assertEqual(store.stats()['jobs'], 1)
            self.assertTrue(all('/api/jobPosting/' not in call.args[0] for call in client.get.call_args_list))
            report = json.loads((Path(tmp) / 'exports/run-report.json').read_text())
            self.assertEqual(report['skipped_existing'], 1)


if __name__ == '__main__':
    unittest.main()
