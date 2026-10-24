import unittest
from unittest.mock import Mock, patch

from Jobs_scrapper.job_agent.browser import BrowserClient, public_url
from Jobs_scrapper.job_agent.http import AccessBlocked, RateLimited
from Jobs_scrapper.job_agent.parse import parse_job


class BrowserTests(unittest.TestCase):
    def test_cli_hidden_mode_uses_same_browser_client(self):
        import tempfile
        from pathlib import Path
        from Jobs_scrapper.job_agent.__main__ import main
        with tempfile.TemporaryDirectory() as tmp:
            http = Mock(cooldowns={})
            with patch('job_agent.__main__.Client', return_value=http), patch('job_agent.browser.BrowserClient') as browser, patch('job_agent.__main__.collect', return_value=0) as collect:
                self.assertEqual(main(['--database', str(Path(tmp) / 'db'), 'collect', '--browser', '--headless']), 0)
                browser.assert_called_once_with(http, headless=True)
                self.assertIs(collect.call_args.args[2], browser.return_value.__enter__.return_value)

    def test_saved_cooldown_does_not_launch_browser(self):
        import tempfile
        import time
        from pathlib import Path
        from Jobs_scrapper.job_agent.__main__ import main
        with tempfile.TemporaryDirectory() as tmp:
            http = Mock(cooldowns={'www.linkedin.com': time.time() + 900})
            with patch('job_agent.__main__.Client', return_value=http), patch('job_agent.browser.BrowserClient') as browser, patch('job_agent.__main__.collect', return_value=3):
                self.assertEqual(main(['--database', str(Path(tmp) / 'db'), 'collect', '--browser']), 3)
                browser.assert_not_called()

    def test_guest_requests_map_to_regular_public_pages(self):
        self.assertEqual(public_url('https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/123456'),
                         'https://www.linkedin.com/jobs/view/123456')
        self.assertEqual(public_url('https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=Python&start=25'),
                         'https://www.linkedin.com/jobs/search/?keywords=Python&start=25')

    def client(self):
        http = Mock(delay=0, cooldowns={})
        client = BrowserClient(http, read=lambda prompt: 'q')
        client.page = Mock(url='https://www.linkedin.com/jobs/view/123456')
        client.page.goto.return_value = Mock(status=200)
        client.page.content.return_value = '<h1>Engineer</h1>'
        return client, http

    def test_429_is_saved_and_not_retried(self):
        client, http = self.client()
        client.page.goto.return_value = Mock(status=429, headers={'retry-after': '3600'})
        with self.assertRaises(RateLimited):
            client.get('https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/123456')
        http.remember_cooldown.assert_called_once()
        self.assertEqual(client.page.goto.call_count, 1)

    def test_known_cooldown_prevents_browser_navigation(self):
        import time
        client, http = self.client()
        http.cooldowns = {'www.linkedin.com': time.time() + 900}
        with self.assertRaises(RateLimited):
            client.get('https://www.linkedin.com/jobs/view/123456')
        client.page.goto.assert_not_called()

    def test_user_can_cancel_login_prompt(self):
        client, http = self.client()
        client.page.url = 'https://www.linkedin.com/authwall'
        with self.assertRaises(AccessBlocked):
            client.get('https://www.linkedin.com/jobs/view/123456')

    def test_external_enrichment_uses_http_client(self):
        client, http = self.client()
        http.get.return_value = ('<p>Jobs</p>', 'https://example.com/careers')
        self.assertEqual(client.get('https://example.com/careers'), http.get.return_value)
        client.page.goto.assert_not_called()

    def test_signed_in_job_layout(self):
        html = '''<h1 class="job-details-jobs-unified-top-card__job-title">Data Scientist</h1>
        <div class="job-details-jobs-unified-top-card__company-name"><a href="https://www.linkedin.com/company/acme">Acme</a></div>
        <div id="job-details">Python role. Contact jobs@acme.example</div>'''
        job = parse_job(html, 'https://www.linkedin.com/jobs/view/123456')
        self.assertEqual(job['title'], 'Data Scientist')
        self.assertEqual(job['company'], 'Acme')
        self.assertEqual(job['contacts'][0]['value'], 'jobs@acme.example')
