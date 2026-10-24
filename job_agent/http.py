"""Bounded public requests; redirects are validated before following."""
import ipaddress
import json
import logging
import math
from pathlib import Path
from email.utils import parsedate_to_datetime
import socket
import time
from urllib.parse import urlsplit, urljoin
import requests


class AccessBlocked(RuntimeError):
    pass


class RateLimited(AccessBlocked):
    def __init__(self, url, retry_at, cached=False):
        self.retry_at = retry_at
        self.cached = cached
        super().__init__(f'Rate limited at {url}; retry no earlier than '
                         f'{time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(retry_at))}')


def retry_delay(header, attempt):
    # A missing/invalid hint gets a conservative cooldown, not a rapid retry.
    try:
        value = float(header)
        if not math.isfinite(value) or value < 0:
            raise ValueError('Invalid delay')
        return max(1, value)
    except (ValueError, TypeError, OverflowError):
        try:
            return max(1, parsedate_to_datetime(header).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError, AttributeError):
            return 900 * (2 ** attempt)


def validate_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Only public HTTP(S) URLs without credentials are supported')
    if parsed.port not in (None, 80, 443):
        raise ValueError('Nonstandard ports are not supported')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Private or reserved network targets are not supported')


class Client:
    def __init__(self, delay=3, timeout=25, state_path=None, legacy_state_paths=()):
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers['User-Agent'] = 'JobCollector/1.0 (public job research)'
        self.delay = max(0, delay)
        self.timeout = timeout
        self.last_request = 0
        self.state_path = Path(state_path) if state_path else None
        self.cooldowns = {}
        for path in [self.state_path, *legacy_state_paths]:
            if path and Path(path).exists():
                state = json.loads(Path(path).read_text(encoding='utf-8-sig'))
                if not isinstance(state, dict):
                    raise ValueError(f'Invalid cooldown file: {path}')
                for host, deadline in state.items():
                    if not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
                        raise ValueError(f'Invalid cooldown time: {path}')
                    self.cooldowns[host] = max(self.cooldowns.get(host, 0), deadline)

    def remember_cooldown(self, host, retry_at):
        self.cooldowns[host] = retry_at
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.cooldowns, indent=2), encoding='utf-8')
            temporary.replace(self.state_path)

    def get(self, url):
        for redirect in range(6):
            host = urlsplit(url).hostname
            retry_at = self.cooldowns.get(host, 0)
            if retry_at > time.time():
                raise RateLimited(url, retry_at, cached=True)
            validate_url(url)
            for attempt in range(3):
                time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
                response = self.session.get(url, timeout=self.timeout, allow_redirects=False, stream=True)
                if response.status_code == 429:
                    wait = retry_delay(response.headers.get('Retry-After'), attempt)
                    response.close()
                    if attempt < 2 and wait <= 30:
                        logging.getLogger('job_agent').warning('HTTP 429; waiting %.0f seconds before retry %d/2', wait, attempt + 1)
                        time.sleep(wait)
                        continue
                    retry_at = time.time() + max(wait, 900 if attempt == 2 else 0)
                    self.remember_cooldown(host, retry_at)
                    raise RateLimited(url, retry_at)
                if response.status_code in (401, 403, 999):
                    response.close()
                    raise AccessBlocked(f'Access blocked (HTTP {response.status_code}) at {url}')
                if response.status_code in (500, 502, 503, 504) and attempt < 2:
                    response.close()
                    time.sleep(2 ** attempt)
                    continue
                break
            if response.status_code in (301, 302, 303, 307, 308):
                target = response.headers.get('Location')
                response.close()
                if not target:
                    raise ValueError('Redirect has no target')
                url = urljoin(url, target)
                if any(p in urlsplit(url).path.lower() for p in ('/authwall', '/login', '/checkpoint')):
                    raise AccessBlocked('Login or checkpoint encountered')
                continue
            try:
                response.raise_for_status()
                content_type = response.headers.get('Content-Type', '').lower()
                if content_type and not any(t in content_type for t in ('text/html', 'application/xhtml')):
                    raise ValueError(f'Unsupported page type: {content_type}')
                chunks, total = [], 0
                for chunk in response.iter_content(65536):
                    total += len(chunk)
                    if total > 3_000_000:
                        raise ValueError('Page exceeds 3 MB limit')
                    chunks.append(chunk)
                encoding = response.encoding if 'charset=' in content_type else 'utf-8'
                html = b''.join(chunks).decode(encoding or 'utf-8', errors='replace')
                if any(marker in html.lower() for marker in ('<title>authwall', 'security verification', 'sign in to linkedin')):
                    raise AccessBlocked('Login or security page returned')
                return html, url
            finally:
                response.close()
        raise ValueError('Too many redirects')

    def close(self):
        self.session.close()
