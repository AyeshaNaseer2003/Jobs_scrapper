import argparse
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from job_agent.__main__ import collect, enrich, main
from job_agent.http import Client, AccessBlocked
from job_agent.parse import parse_job
from job_agent.store import Store

SAMPLE = Path(__file__).resolve().parent / 'fixtures/sample-job.html'


class WorkflowTests(unittest.TestCase):
    def test_external_apply_redirect_is_enriched(self):
        html = SAMPLE.read_text().replace('https://example.com/careers/sample', 'https://www.linkedin.com/jobs/view/externalApply/999999999?url=https%3A%2F%2Fexample.com%2Fcareers%2Fsample')
        job = parse_job(html, 'https://www.linkedin.com/jobs/view/999999999')
        self.assertIn('https://example.com/careers/sample', job['external_links'])

    def test_invalid_env_enrichment_limit_rejected(self):
        from job_agent.__main__ import parser
        with patch.dict('os.environ', {'ENRICHMENT_LIMIT': '-2'}), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser().parse_args(['collect'])

    def test_pagination_uses_actual_result_count(self):
        from urllib.parse import urlsplit, parse_qs
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(keywords='Python', location='Pakistan', max_jobs=2,
                hours=24, enrichment_limit=0, phone_region='PK', export_dir=Path(tmp) / 'out')
            client = Mock()
            client.get.side_effect = [
                ('<a href="https://www.linkedin.com/jobs/view/111111">A</a>', 'https://www.linkedin.com'),
                (SAMPLE.read_text(), 'https://www.linkedin.com'),
                ('<a href="https://www.linkedin.com/jobs/view/222222">B</a>', 'https://www.linkedin.com'),
                (SAMPLE.read_text(), 'https://www.linkedin.com')]
            with Store(Path(tmp) / 'db') as store, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(collect(args, store, client), 0)
                self.assertEqual(store.stats()['jobs'], 2)
            second = client.get.call_args_list[2].args[0]
            self.assertEqual(parse_qs(urlsplit(second).query)['start'], ['1'])

    def test_collection_enrichment_and_repeated_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(keywords='Python', location='Pakistan', max_jobs=1,
                hours=24, enrichment_limit=2, phone_region='PK', export_dir=Path(tmp) / 'exports')
            listing = '<a href="https://www.linkedin.com/jobs/view/999999999">Job</a>'
            client = Mock()
            with Store(Path(tmp) / 'jobs.db') as store, contextlib.redirect_stdout(io.StringIO()):
                for _ in range(2):
                    client.get.side_effect = [(listing, 'https://www.linkedin.com'),
                        (SAMPLE.read_text(), 'https://www.linkedin.com'),
                        ('<p>Recruitment: talent@example.com</p>', 'https://example.com/careers/sample')]
                    self.assertEqual(collect(args, store, client), 0)
                self.assertEqual(store.stats(), {'jobs': 1, 'contacts': 2, 'runs': 2})
                contacts = store.records()[0]['contacts']
                self.assertTrue(any(c['value'] == 'talent@example.com' and c['source_url'] == 'https://example.com/careers/sample' for c in contacts))
                self.assertTrue((Path(tmp) / 'exports/contacts.csv').exists())

    def test_blocked_collection_records_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(keywords='Python', location='Pakistan', max_jobs=1,
                hours=24, enrichment_limit=0, phone_region='PK', export_dir=Path(tmp) / 'exports')
            client = Mock()
            client.get.side_effect = AccessBlocked('blocked')
            with Store(Path(tmp) / 'jobs.db') as store, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(collect(args, store, client), 2)
                self.assertEqual(store.stats()['runs'], 1)
                self.assertEqual(store.stats()['jobs'], 0)

    def test_enrichment_failure_preserves_job(self):
        job = parse_job(SAMPLE.read_text(), 'https://www.linkedin.com/jobs/view/999999999')
        client = Mock()
        client.get.side_effect = ValueError('private target')
        enrich(job, client, 2, 'PK')
        self.assertEqual(job['enrichment'][0]['status'], 'error')
        self.assertEqual(job['contacts'][0]['value'], 'jobs@example.com')

    def test_redirect_to_private_target_never_requested(self):
        client = Client(delay=0)
        response = Mock(status_code=302, headers={'Location': 'http://127.0.0.1/'})
        with patch('job_agent.http.validate_url', side_effect=[None, ValueError('private')]), patch.object(client.session, 'get', return_value=response) as get:
            with self.assertRaises(ValueError):
                client.get('https://example.com')
            self.assertEqual(get.call_count, 1)

    def test_html_import_offline(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            with patch.object(Client, 'get', side_effect=AssertionError('must be offline')):
                self.assertEqual(main(['--database', str(Path(tmp) / 'db.sqlite3'), '--export-dir', str(Path(tmp) / 'out'),
                    'import-html', str(SAMPLE), '--url', 'https://www.linkedin.com/jobs/view/999999999']), 0)


if __name__ == '__main__':
    unittest.main()
