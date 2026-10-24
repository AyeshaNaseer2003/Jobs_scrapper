"""Visible browser collection. No stealth, proxy rotation or verification bypass."""
import time
from urllib.parse import urlsplit, urlunsplit

import requests

from .http import AccessBlocked, RateLimited, retry_delay


def public_url(url):
    parsed = urlsplit(url)
    path = parsed.path
    if path == '/jobs-guest/jobs/api/seeMoreJobPostings/search':
        path = '/jobs/search/'
    elif path.startswith('/jobs-guest/jobs/api/jobPosting/'):
        path = '/jobs/view/' + path.rsplit('/', 1)[1]
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ''))


def is_login(url):
    return any(part in urlsplit(url).path.lower() for part in ('/login', '/authwall', '/checkpoint', '/uas/'))


class BrowserClient:
    def __init__(self, http, read=None, headless=False):
        self.http = http
        self.read = read or input
        self.headless = headless
        self.driver = None
        self.browser = None
        self.page = None
        self.last_request = 0

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright, Error
        except ImportError:
            raise ValueError('Browser mode needs a one-time free setup: .\\run.cmd setup-browser') from None
        self.driver = sync_playwright().start()
        try:
            for channel in ('msedge', 'chrome', None):
                try:
                    self.browser = self.driver.chromium.launch(channel=channel, headless=self.headless)
                    break
                except Error:
                    continue
            if self.browser is None:
                raise ValueError('No supported browser could open. Install Edge or Chrome, then run .\\run.cmd again.')
            context = self.browser.new_context(accept_downloads=False)
            self.page = context.new_page()
            return self
        except BaseException:
            self.close()
            raise

    def get(self, url):
        host = urlsplit(url).hostname or ''
        if not (host == 'linkedin.com' or host.endswith('.linkedin.com')):
            return self.http.get(url)
        deadline = self.http.cooldowns.get(host, 0)
        if deadline > time.time():
            raise RateLimited(url, deadline, cached=True)
        target = public_url(url)
        from playwright.sync_api import Error, TimeoutError
        try:
            time.sleep(max(0, self.http.delay - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            response = self.page.goto(target, wait_until='domcontentloaded', timeout=45000)
            self.check_response(response, target, host)
            if is_login(self.page.url):
                if self.headless:
                    raise AccessBlocked('LinkedIn requires manual sign-in; rerun browser mode without --headless')
                print('\nLinkedIn opened a sign-in or verification page.')
                print('Use the browser yourself if you want to continue. Your password is not read or saved by this tool.')
                try:
                    answer = self.read('After finishing in the browser, press Enter to continue, or q to stop: ').strip().lower()
                except EOFError:
                    raise AccessBlocked('No interactive terminal available for sign-in; collection stopped') from None
                if answer == 'q' or is_login(self.page.url):
                    raise AccessBlocked('Sign-in or verification was not completed; collection stopped')
                if self.page.url.split('?')[0].rstrip('/') != target.split('?')[0].rstrip('/'):
                    response = self.page.goto(target, wait_until='domcontentloaded', timeout=45000)
                    self.check_response(response, target, host)
                    if is_login(self.page.url):
                        raise AccessBlocked('LinkedIn still requires sign-in or verification')
            current_host = urlsplit(self.page.url).hostname or ''
            if not (current_host == 'linkedin.com' or current_host.endswith('.linkedin.com')):
                raise AccessBlocked('LinkedIn redirected away from the job page')
            selector = 'a[href*="/jobs/view/"]' if '/jobs/search' in target else '.show-more-less-html__markup, .description__text, #job-details'
            try:
                self.page.locator(selector).first.wait_for(state='attached', timeout=15000)
            except TimeoutError:
                pass  # Parser will report an empty/changed page honestly.
            return self.page.content(), self.page.url
        except Error as exc:
            raise requests.ConnectionError(f'Browser could not load the page: {exc}') from exc

    def check_response(self, response, url, host):
        if response is None:
            return
        if response.status == 429:
            retry_at = time.time() + retry_delay(response.headers.get('retry-after'), 0)
            self.http.remember_cooldown(host, retry_at)
            raise RateLimited(url, retry_at)
        if response.status in (401, 403, 999):
            raise AccessBlocked(f'LinkedIn refused browser access (HTTP {response.status})')
        if response.status >= 400:
            raise requests.HTTPError(f'Browser received HTTP {response.status} at {url}')

    def close(self):
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self.driver:
                self.driver.stop()

    def __exit__(self, *args):
        self.close()
