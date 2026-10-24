"""Run with python -m job_agent."""
import argparse
import json
import logging
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlencode, urlsplit

from dotenv import load_dotenv
import requests

from .http import Client, AccessBlocked, RateLimited
from .parse import parse_job, parse_search, extract_contacts
from .store import Store, now

LOG = logging.getLogger('job_agent')
ROOT = Path(__file__).resolve().parent.parent


def enrich(job, client, limit, region):
    # Follow explicit application/careers/contact links only, never crawl a domain.
    candidates = [url for url in job['external_links'] if any(
        word in url.lower() for word in ('career', '/job', 'apply', 'recruit', 'contact', 'greenhouse.io', 'lever.co', 'workday'))]
    for url in candidates[:limit]:
        try:
            html, final = client.get(url)
            job['contacts'].extend(extract_contacts(html, final, region))
            job['enrichment'].append({'url': url, 'final_url': final, 'status': 'ok'})
        except (requests.RequestException, ValueError, OSError, AccessBlocked) as exc:
            job['enrichment'].append({'url': url, 'status': 'error', 'error': str(exc)})
            LOG.warning('Enrichment failed: %s', exc)


def collect(args, store, client):
    if getattr(args, 'friendly', False):
        from .display import file_logging
        with file_logging(args.export_dir):
            return _collect(args, store, client)
    return _collect(args, store, client)


def _collect(args, store, client):
    started = now()
    summary = {'saved': 0, 'failed': 0, 'blocked': False, 'errors': [], 'keywords': args.keywords, 'location': args.location,
               'hours': args.hours, 'started': started, 'skipped_existing': 0, 'status': 'running',
               'requested_mode': 'browser' if getattr(args, 'browser', False) else 'http',
               'headless': bool(getattr(args, 'headless', False))}
    existing = {job['url'] for job in store.records()} if getattr(args, 'resume', False) else set()
    seen = set()
    try:
        offset = 0
        for _ in range(args.max_jobs + 1):
            query = urlencode({'keywords': args.keywords, 'location': args.location,
                               'start': offset, 'f_TPR': f'r{args.hours * 3600}'})
            html, _ = client.get('https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?' + query)
            page_links = parse_search(html)
            links = [url for url in page_links if url not in seen]
            offset += len(page_links)
            if not links:
                if not seen:
                    LOG.warning('No job links found: no matches, access restrictions, or changed page layout.')
                break
            for url in links:
                if len(seen) >= args.max_jobs:
                    break
                seen.add(url)
                if url in existing:
                    summary['skipped_existing'] += 1
                    continue
                try:
                    job_id = url.rsplit('/', 1)[1]
                    detail, _ = client.get('https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/' + job_id)
                    job = parse_job(detail, url, args.phone_region)
                    enrich(job, client, args.enrichment_limit, args.phone_region)
                    store.save(job)
                    summary['saved'] += 1
                    if getattr(args, 'friendly', False):
                        print(f"  {summary['saved']}. {job['title']} - {job['company']}")
                    LOG.info('Saved %s at %s (%s)', job['title'], job['company'], job_id)
                except AccessBlocked:
                    raise
                except (requests.RequestException, ValueError, OSError) as exc:
                    summary['failed'] += 1
                    summary['errors'].append({'url': url, 'error': str(exc)})
                    LOG.warning('Job failed %s: %s', url, exc)
            if len(seen) >= args.max_jobs:
                break
    except (AccessBlocked, requests.RequestException, ValueError, OSError) as exc:
        summary['blocked'] = isinstance(exc, AccessBlocked)
        if isinstance(exc, RateLimited):
            summary['retry_at'] = exc.retry_at
            summary['cached_cooldown'] = exc.cached
            summary['retry_after_seconds'] = max(0, int(exc.retry_at - time.time()) + 1)
        summary['errors'].append({'error': str(exc)})
        LOG.error('Collection stopped: %s', exc)
    finally:
        summary['attempted'] = len(seen)
        summary['finished'] = now()
        summary['status'] = ('rate_limited' if 'retry_at' in summary else
                             'blocked' if summary['blocked'] else
                             'partial' if summary['errors'] else
                             'no_results' if not seen else 'success')
        summary['stored_jobs'] = store.stats()['jobs']
        summary['exported'] = summary['stored_jobs'] > 0
        store.record_run(started, summary)
        directory = Path(args.export_dir)
        directory.mkdir(parents=True, exist_ok=True)
        if summary['exported']:
            store.export(directory)
        (directory / 'run-report.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    if getattr(args, 'friendly', False):
        from .display import show_result
        show_result(summary, args.export_dir)
    else:
        print(json.dumps(summary, indent=2))
    return 3 if 'retry_at' in summary else 2 if summary['blocked'] or summary['errors'] else 0


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('Must be a positive integer')
    return number


def nonnegative(value):
    number = float(value)
    if not 0 <= number <= 86400:
        raise argparse.ArgumentTypeError('Must be between 0 and 86400')
    return number


def enrichment_limit(value):
    number = int(value)
    if not 0 <= number <= 10:
        raise argparse.ArgumentTypeError('Enrichment limit must be between 0 and 10')
    return number


def parser():
    load_dotenv(ROOT / '.env')
    p = argparse.ArgumentParser(description='Public job collector with SQLite storage and contact provenance')
    p.add_argument('--database', default=os.getenv('DATABASE_PATH', str(ROOT / 'data/jobs.sqlite3')))
    p.add_argument('--export-dir', default=os.getenv('EXPORT_DIR', str(ROOT / 'data/exports')))
    p.add_argument('--phone-region', default=os.getenv('PHONE_REGION', 'PK'))
    p.add_argument('--delay', type=nonnegative, default=os.getenv('REQUEST_DELAY', '3'))
    commands = p.add_subparsers(dest='command', required=True)
    for command in ('collect', 'watch'):
        sub = commands.add_parser(command)
        sub.add_argument('--keywords', default=os.getenv('JOB_KEYWORDS', 'software engineer'))
        sub.add_argument('--location', default=os.getenv('JOB_LOCATION', 'Pakistan'))
        sub.add_argument('--max-jobs', type=positive, default=os.getenv('MAX_JOBS', '25'))
        sub.add_argument('--hours', type=positive, default=168)
        sub.add_argument('--resume', action='store_true', help='Skip details for jobs already saved in this database')
        sub.add_argument('--enrichment-limit', type=enrichment_limit, default=os.getenv('ENRICHMENT_LIMIT', '2'))
        if command == 'collect':
            sub.add_argument('--browser', action='store_true', help='Use a visible Edge/Chrome browser instead of guest HTTP requests')
            sub.add_argument('--headless', action='store_true', help='Run browser mode with its window hidden (cannot handle manual sign-in)')
        if command == 'watch':
            sub.add_argument('--interval', type=positive, default=os.getenv('RUN_INTERVAL', '3600'))
    sub = commands.add_parser('import-html', help='Import one saved job detail page')
    sub.add_argument('file', type=Path)
    sub.add_argument('--url', required=True, help='Original LinkedIn job URL')
    sub.add_argument('--enrich', action='store_true', help='Fetch explicitly linked careers pages')
    commands.add_parser('export')
    commands.add_parser('stats')
    commands.add_parser('test', help='Run the offline automated test suite')
    commands.add_parser('setup-browser', help='Install the free browser automation library')
    return p


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    argv = list(sys.argv[1:] if argv is None else argv)
    interactive = not argv
    if not argv:
        from .interactive import wizard
        try:
            argv = wizard()
        except (EOFError, KeyboardInterrupt):
            print('\nCancelled. No search started.')
            return 130
        if argv is None:
            return 0
    args = parser().parse_args(argv)
    args.friendly = interactive
    if args.command == 'setup-browser':
        import subprocess
        return subprocess.call([sys.executable, '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')])
    if args.command == 'test':
        import unittest
        suite = unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parent / 'tests'))
        return 0 if unittest.TextTestRunner(verbosity=2, buffer=True).run(suite).wasSuccessful() else 1
    data_root = ROOT / 'data'
    client = Client(args.delay, state_path=data_root / 'http-state.json',
                    legacy_state_paths=[*data_root.rglob('*.http-state.json'),
                                        Path(args.database).with_suffix('.http-state.json')])
    try:
        with Store(args.database) as store:
            if args.command == 'stats':
                print(json.dumps(store.stats(), indent=2))
            elif args.command == 'export':
                for path in store.export(args.export_dir):
                    print(path)
            elif args.command == 'import-html':
                job = parse_job(args.file.read_text(encoding='utf-8'), args.url, args.phone_region)
                if args.enrich:
                    enrich(job, client, 2, args.phone_region)
                store.save(job)
                store.export(args.export_dir)
                print(f"Saved {job['title']} ({job['job_id']}) with {len(job['contacts'])} contacts")
            elif args.command == 'collect':
                if args.browser and args.friendly and client.cooldowns.get('www.linkedin.com', 0) > time.time():
                    from .interactive import wait_for_cooldown
                    try:
                        wait_for_cooldown(client.cooldowns['www.linkedin.com'])
                    except EOFError:
                        pass  # Report the saved cooldown without attempting a request.
                if args.browser and client.cooldowns.get('www.linkedin.com', 0) <= time.time():
                    from .browser import BrowserClient
                    if args.friendly:
                        print('Opening Edge/Chrome now. If a sign-in page appears, follow the terminal instructions.\n')
                    with BrowserClient(client, headless=args.headless) as browser:
                        return collect(args, store, browser)
                return collect(args, store, client)
            elif args.command == 'watch':
                if args.interval < 900:
                    raise ValueError('Watch interval must be at least 900 seconds')
                while True:
                    result = collect(args, store, client)
                    if result and result != 3:
                        LOG.error('Watch stopped after a collection error; review the run before restarting.')
                        return result
                    wait = max(args.interval, max(client.cooldowns.values(), default=0) - time.time() + 1)
                    LOG.info('Next collection in %.0f seconds; Ctrl+C to stop', wait)
                    time.sleep(wait)
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError, requests.RequestException) as exc:
        LOG.error('%s', exc)
        return 1
    finally:
        client.close()


if __name__ == '__main__':
    raise SystemExit(main())
