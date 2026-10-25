"""Durable subtitle jobs in app data; no extra files beside downloaded videos."""
import json
import sqlite3
from pathlib import Path

class SubtitleJobStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, job):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO jobs (id, payload) VALUES (?, ?)', (job['id'], json.dumps(job, ensure_ascii=False)))

    def remove(self, job_id):
        with self.connect() as db:
            db.execute('DELETE FROM jobs WHERE id = ?', (job_id,))

    def load(self):
        with self.connect() as db:
            rows = db.execute('SELECT id, payload FROM jobs ORDER BY rowid').fetchall()
        jobs = []
        for job_id, payload in rows:
            try:
                job = json.loads(payload)
                if isinstance(job, dict) and job.get('id') == job_id and job.get('status') in ('queued', 'running', 'done', 'error'):
                    jobs.append(job)
            except (ValueError, TypeError):
                continue
        return sorted(jobs, key=lambda job: job.get('created_at', 0))
