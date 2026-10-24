"""Persistent records, contact provenance and spreadsheet-safe exports."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_cell(value):
    value = str(value or '')
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS contacts (
                job_id TEXT NOT NULL REFERENCES jobs(job_id), kind TEXT NOT NULL,
                value TEXT NOT NULL, source_url TEXT NOT NULL,
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                PRIMARY KEY(job_id,kind,value,source_url));
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY, started TEXT, finished TEXT, summary TEXT);
        ''')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def save(self, job):
        timestamp = now()
        with self.db:
            self.db.execute('''INSERT INTO jobs VALUES(?,?,?,?) ON CONFLICT(job_id)
                DO UPDATE SET payload=excluded.payload,last_seen=excluded.last_seen''',
                (job['job_id'], json.dumps(job, ensure_ascii=False), timestamp, timestamp))
            for c in job.get('contacts', []):
                self.db.execute('''INSERT INTO contacts VALUES(?,?,?,?,?,?)
                    ON CONFLICT(job_id,kind,value,source_url) DO UPDATE SET last_seen=excluded.last_seen''',
                    (job['job_id'], c['kind'], c['value'], c['source_url'], timestamp, timestamp))

    def records(self):
        records = []
        for job_id, payload, first, last in self.db.execute('SELECT * FROM jobs ORDER BY last_seen DESC'):
            job = json.loads(payload)
            job.update(first_seen=first, last_seen=last)
            job['contacts'] = [dict(zip(('kind', 'value', 'source_url', 'first_seen', 'last_seen'), row))
                for row in self.db.execute('SELECT kind,value,source_url,first_seen,last_seen FROM contacts WHERE job_id=? ORDER BY kind,value', (job_id,))]
            records.append(job)
        return records

    def record_run(self, started, summary):
        with self.db:
            self.db.execute('INSERT INTO runs(started,finished,summary) VALUES(?,?,?)', (started, now(), json.dumps(summary)))

    def stats(self):
        return {name: self.db.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] for name in ('jobs', 'contacts', 'runs')}

    def export(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        jobs_path, json_path, contacts_path = [directory / name for name in ('jobs.csv', 'jobs.json', 'contacts.csv')]
        rows = self.records()
        fields = ['job_id', 'title', 'company', 'location', 'date_posted', 'url', 'salary', 'description', 'criteria', 'recruiters', 'external_links', 'first_seen', 'last_seen']
        with jobs_path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: safe_cell(json.dumps(row.get(k), ensure_ascii=False) if isinstance(row.get(k), (dict, list)) else row.get(k)) for k in fields})
        json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        with contacts_path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['job_id', 'kind', 'value', 'source_url', 'first_seen', 'last_seen'])
            writer.writeheader()
            for row in rows:
                for contact in row['contacts']:
                    writer.writerow({k: safe_cell(v) for k, v in dict(job_id=row['job_id'], **contact).items()})
        return jobs_path, json_path, contacts_path
