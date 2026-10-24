"""Plain terminal results; technical detail stays in the run's files."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path

PAKISTAN_TIME = timezone(timedelta(hours=5))


@contextmanager
def file_logging(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('job_agent')
    handler = logging.FileHandler(directory / 'run.log', encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    previous = logger.propagate
    logger.addHandler(handler)
    logger.propagate = False
    try:
        yield
    finally:
        logger.removeHandler(handler)
        logger.propagate = previous
        handler.close()


def show_result(summary, directory):
    directory = Path(directory)
    saved = summary['saved']
    status = summary['status']
    print()
    if saved:
        print(f'Saved {saved} jobs.' if saved != 1 else 'Saved 1 job.')
        print(f'Open your jobs: {directory / "jobs.csv"}')
        print(f'Contact details: {directory / "contacts.csv"}')
    elif summary.get('skipped_existing'):
        print('These jobs were already saved.')
        print(f'Open your jobs: {directory / "jobs.csv"}')
    else:
        print('No jobs were collected in this run.')
        if summary.get('stored_jobs', 0):
            print(f'Earlier saved jobs: {directory / "jobs.csv"}')
        elif summary.get('exported') is False:
            print('No spreadsheet was created because no job data was available.')
    if status == 'rate_limited':
        retry = datetime.fromtimestamp(summary['retry_at'], PAKISTAN_TIME)
        if summary.get('cached_cooldown'):
            print('This search was paused by a saved cooldown from an earlier run.')
            print('No new request was sent to LinkedIn.')
        else:
            print('LinkedIn temporarily limited access. This can happen even on the first request.')
        print(f'Try again after {retry:%d %b %Y, %H:%M} Pakistan time (UTC+05:00).')
        print('This is the earliest retry time, not a guarantee that LinkedIn will allow access.')
        print('Run .\\run.cmd again with the same search. Any saved jobs are kept.')
    elif status == 'blocked':
        print('LinkedIn refused automated access. Try later or use a saved job page.')
    elif status == 'partial':
        print('Some requests failed. Any successfully collected jobs are kept.')
    elif status == 'no_results':
        print('No matching job links were returned. Try broader keywords or another location.')
        print('LinkedIn access restrictions can also cause this result.')
    print(f'Run details: {directory / "run-report.json"}')
