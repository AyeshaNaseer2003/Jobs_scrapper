import contextlib
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from Jobs_scrapper.job_agent.display import show_result


class DisplayTests(unittest.TestCase):
    def test_saved_cooldown_is_not_presented_as_new_server_block(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            show_result({'status': 'rate_limited', 'saved': 0, 'retry_at': 1792797587,
                         'cached_cooldown': True}, Path(tmp))
        self.assertIn('earlier run', out.getvalue())
        self.assertIn('No new request', out.getvalue())

    def test_rate_limit_has_local_retry_and_no_json(self):
        retry_at = datetime(2026, 10, 24, 3, 42, tzinfo=timezone(timedelta(hours=5))).timestamp()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            show_result({'status': 'rate_limited', 'saved': 0, 'retry_at': retry_at}, Path(tmp))
        text = out.getvalue()
        self.assertIn('03:42', text)
        self.assertIn('UTC+05:00', text)
        self.assertIn('No jobs were collected', text)
        self.assertNotIn('"retry_at"', text)
        self.assertNotIn('jobs.csv', text)

    def test_success_shows_file_and_count(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            show_result({'status': 'success', 'saved': 3}, Path(tmp))
        self.assertIn('Saved 3 jobs', out.getvalue())
        self.assertIn('jobs.csv', out.getvalue())

    def test_interactive_block_writes_technical_details_only_to_files(self):
        import argparse
        import time
        from Jobs_scrapper.job_agent.__main__ import collect
        from Jobs_scrapper.job_agent.http import RateLimited
        from Jobs_scrapper.job_agent.store import Store
        args = argparse.Namespace(keywords='data science', location='Pakistan', max_jobs=1,
            hours=720, friendly=True)
        client = Mock()
        client.get.side_effect = RateLimited('https://www.linkedin.com/test', time.time() + 900)
        with tempfile.TemporaryDirectory() as tmp:
            args.export_dir = Path(tmp)
            with Store(Path(tmp) / 'jobs.db') as store, contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(collect(args, store, client), 3)
            self.assertNotIn('"retry_at"', out.getvalue())
            self.assertNotIn('https://www.linkedin.com/test', out.getvalue())
            self.assertEqual(err.getvalue(), '')
            self.assertIn('https://www.linkedin.com/test', (Path(tmp) / 'run.log').read_text())
            self.assertTrue((Path(tmp) / 'run-report.json').exists())
