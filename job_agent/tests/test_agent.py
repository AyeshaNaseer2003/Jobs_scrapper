import json
from pathlib import Path
import tempfile
import unittest

from Jobs_scrapper.job_agent.parse import parse_job, parse_search, extract_contacts
from Jobs_scrapper.job_agent.store import Store
from Jobs_scrapper.job_agent.http import Client, AccessBlocked, validate_url


HTML = '''<html><h1 class="top-card-layout__title">Python Developer</h1>
<a class="topcard__org-name-link" href="https://www.linkedin.com/company/acme">Acme</a>
<span class="topcard__flavor--bullet">Lahore</span>
<div class="show-more-less-html__markup">Build Python apps. Email jobs@acme.example.
<a href="mailto:talent@acme.example?subject=Role">Contact</a>
<a href="tel:+442079460958">Call</a>
<a href="https://acme.example/careers/123">Apply</a></div>
<li class="description__job-criteria-item"><h3>Employment type</h3><span>Full-time</span></li>
<script type="application/ld+json">{"@type":"JobPosting","datePosted":"2026-10-20","baseSalary":{"currency":"PKR","value":{"minValue":100000,"maxValue":200000}},"skills":["Python","SQL"]}</script>
</html>'''


class ParsingTests(unittest.TestCase):
    def test_fields_and_contacts_have_provenance(self):
        job = parse_job(HTML, 'https://www.linkedin.com/jobs/view/123456')
        self.assertEqual(job['job_id'], '123456')
        self.assertEqual(job['title'], 'Python Developer')
        self.assertEqual(job['company'], 'Acme')
        self.assertEqual(job['criteria']['Employment type'], 'Full-time')
        self.assertEqual(job['date_posted'], '2026-10-20')
        self.assertEqual(job['metadata']['skills'], ['Python', 'SQL'])
        self.assertIn('https://acme.example/careers/123', job['external_links'])
        self.assertEqual({c['value'] for c in job['contacts'] if c['kind'] == 'email'},
                         {'jobs@acme.example', 'talent@acme.example'})
        self.assertTrue(all(c['source_url'] == job['url'] for c in job['contacts']))

    def test_search_deduplicates_and_ignores_bad_links(self):
        html = '<a href="https://www.linkedin.com/jobs/view/dev-123456?x=1">a</a>' * 2
        html += '<a href="https://evil.example/jobs/view/999999">b</a>'
        self.assertEqual(parse_search(html), ['https://www.linkedin.com/jobs/view/123456'])

    def test_jsonld_only_and_missing_fields(self):
        html = '<script type="application/ld+json">' + json.dumps({'@graph': [
            {'@type': 'JobPosting', 'title': 'Engineer', 'hiringOrganization': {'name': 'Co'},
             'description': '<p>jobs@co.example</p>', 'jobLocation': {'address': {'addressLocality': 'Karachi'}}}
        ]}) + '</script>'
        job = parse_job(html, 'https://www.linkedin.com/jobs/view/123456')
        self.assertEqual(job['title'], 'Engineer')
        self.assertEqual(job['location'], 'Karachi')
        self.assertEqual(job['contacts'][0]['value'], 'jobs@co.example')
        self.assertEqual(job['recruiters'], [])

    def test_salary_and_script_not_contacts(self):
        contacts = extract_contacts('<p>Salary 100000 to 200000</p><script>hidden@x.example</script>', 'https://co.example')
        self.assertEqual(contacts, [])

    def test_labelled_local_phone_is_extracted_but_salary_is_not(self):
        contacts = extract_contacts('<p>Salary 03001234567. Call: 0300 1234567</p>', 'https://co.example', 'PK')
        self.assertEqual([c['value'] for c in contacts], ['+923001234567'])

    def test_prefers_description_inner_markup_and_company_link(self):
        html = HTML.replace('<div class="show-more-less-html__markup">', '<div class="description__text"><div class="show-more-less-html__markup">').replace('</div>\n<li', '</div><button>Show more</button></div>\n<li')
        job = parse_job(html, 'https://www.linkedin.com/jobs/view/123456')
        self.assertNotIn('Show more', job['description'])
        self.assertEqual(job['company_url'], 'https://www.linkedin.com/company/acme')


class StorageTests(unittest.TestCase):
    def test_upsert_keeps_first_seen_and_contacts_and_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Store(Path(tmp) / 'jobs.db') as store:
                job = parse_job(HTML, 'https://www.linkedin.com/jobs/view/123456')
                store.save(job)
                first = store.records()[0]['first_seen']
                job['title'] = '=HYPERLINK("evil")'
                store.save(job)
                rows = store.records()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['first_seen'], first)
                self.assertEqual(len(rows[0]['contacts']), 3)
                paths = store.export(Path(tmp) / 'export')
                self.assertIn("'=HYPERLINK", paths[0].read_text(encoding='utf-8-sig'))
                self.assertEqual(len(json.loads(paths[1].read_text())), 1)


class NetworkTests(unittest.TestCase):
    def test_utf8_without_explicit_charset(self):
        from unittest.mock import Mock, patch
        client = Client(delay=0)
        response = Mock(status_code=200, headers={'Content-Type': 'text/html'}, encoding='ISO-8859-1')
        response.iter_content.return_value = ['<p>Islāmābād</p>'.encode('utf-8')]
        with patch('job_agent.http.validate_url'), patch.object(client.session, 'get', return_value=response):
            self.assertEqual(client.get('https://example.com')[0], '<p>Islāmābād</p>')

    def test_rejects_private_urls_and_credentials(self):
        for url in ['http://127.0.0.1', 'http://[::1]', 'file:///tmp/a', 'http://user:pass@example.com']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)

    def test_block_raises_without_retry(self):
        from unittest.mock import Mock, patch
        response = Mock(status_code=429, headers={}, text='blocked')
        client = Client(delay=0)
        with patch('job_agent.http.validate_url'), patch.object(client.session, 'get', return_value=response) as get:
            with self.assertRaises(AccessBlocked):
                client.get('https://www.linkedin.com/jobs/view/123456')
            self.assertEqual(get.call_count, 1)


if __name__ == '__main__':
    unittest.main()
