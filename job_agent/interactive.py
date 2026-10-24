"""Small terminal wizard over the existing command-line interface."""
import hashlib
from pathlib import Path
import re
import time


def wait_for_cooldown(deadline, read=None):
    from datetime import datetime
    from .display import PAKISTAN_TIME
    read = read or input
    resume = datetime.fromtimestamp(deadline, PAKISTAN_TIME)
    print('\nA saved cooldown from an earlier run is still active.')
    print('No new request has been sent to LinkedIn. The browser has not opened yet.')
    print(f'Earliest start: {resume:%d %b %Y, %H:%M} Pakistan time (UTC+05:00).')
    if not ask_yes_no(read, 'Wait here and start the browser automatically when the pause ends'):
        return False
    print('Waiting. Leave this terminal open; Ctrl+C cancels. Access after the wait is not guaranteed.')
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return True
        time.sleep(min(30, remaining))


def ask_number(read, label, default, maximum):
    while True:
        value = read(f'{label} [{default}]: ').strip() or str(default)
        try:
            number = int(value)
            if 1 <= number <= maximum:
                return number
        except ValueError:
            pass
        print(f'Please enter a whole number between 1 and {maximum}.')


def ask_yes_no(read, label, default=True):
    while True:
        value = read(f'{label} [{"Y/n" if default else "y/N"}]: ').strip().lower()
        if not value:
            return default
        if value in ('y', 'yes'):
            return True
        if value in ('n', 'no'):
            return False
        print('Please enter y or n.')


def wizard(read=None):
    from .__main__ import ROOT, parser

    read = read or input
    print('\nJob collection agent\n')
    print('1. Search LinkedIn jobs (default)')
    print('2. Run automated tests (offline)')
    print('3. Exit\n')
    while True:
        choice = read('Choose an option [1]: ').strip() or '1'
        if choice in ('1', '2', '3'):
            break
        print('Please choose 1, 2 or 3.')
    if choice == '3':
        return None
    if choice == '2':
        return ['test']

    defaults = parser().parse_args(['collect'])
    keywords = read(f'Job title or keywords [{defaults.keywords}]: ').strip() or defaults.keywords
    while True:
        location = read(f'City or country (e.g. Lahore, Pakistan, Remote) [{defaults.location}]: ').strip() or defaults.location
        if location.casefold() not in ('yes', 'no', 'y', 'n', 'true', 'false'):
            break
        print('Enter a city or country here, not yes/no. Press Enter to use the default.')
    days = ask_number(read, 'Posted within how many days', 7, 365)
    maximum = ask_number(read, 'Maximum jobs to check', defaults.max_jobs, 1000)

    # Stable search-specific folders make repeat runs update rather than mix queries.
    identity = '\0'.join((keywords.casefold(), location.casefold(), str(days)))
    digest = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]
    label = re.sub(r'[^a-z0-9]+', '-', f'{keywords}-{location}'.lower()).strip('-')[:60] or 'search'
    directory = ROOT / 'data' / 'searches' / f'{label}-{days}d-{digest}'
    print(f'\nYour search: {keywords} | {location} | last {days} days | up to {maximum} jobs')
    print('Published contact details will be collected automatically.')
    if not ask_yes_no(read, 'Start this search'):
        print('Search cancelled. Run .\\run.cmd to enter different search details.')
        return None
    print('\nPreparing your search...\n')
    limit = defaults.enrichment_limit
    return ['--database', str(directory / 'jobs.sqlite3'), '--export-dir', str(directory),
            'collect', '--browser', '--keywords', keywords, '--location', location,
            '--hours', str(days * 24), '--max-jobs', str(maximum), '--enrichment-limit', str(limit)]
