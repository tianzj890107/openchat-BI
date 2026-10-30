"""Bounded, durable delegated analysis tasks; protocol independent."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import fcntl
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid


class TaskService:
    def __init__(self, path, runner, *, workers=2, capacity=8):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        os.chmod(Path(path).parent, 0o700)
        self._owner_file = open(str(path) + '.owner', 'a+b')
        try:
            fcntl.flock(self._owner_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._owner_file.close()
            raise RuntimeError('task_store_already_owned; use a separate volume per replica')
        self.runner = runner
        self.lock = threading.RLock()
        self.slots = threading.BoundedSemaphore(capacity)
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='analytics-task')
        self.cancels = {}
        self.closed = False
        with closing(self._db()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, token TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS events (task_id TEXT NOT NULL, seq INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(task_id,seq))')
            # This service is a single-process owner. Never silently resume a
            # model/tool call whose external effects are unknown after restart.
            db.execute("UPDATE tasks SET status='interrupted', updated=? WHERE status IN ('queued','running','cancelling')", (time.time(),))

        os.chmod(self.path, 0o600)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def submit(self, question):
        if not isinstance(question, str) or not question.strip() or len(question) > 32000:
            raise ValueError('question must contain 1..32000 characters')
        if not self.slots.acquire(blocking=False):
            raise RuntimeError('task_capacity_exhausted; retry later')
        task_id, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
        cancel = threading.Event()
        try:
            with self.lock, closing(self._db()) as db, db:
                if self.closed:
                    raise RuntimeError("task_service_closed")
                now = time.time()
                db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)', (task_id, self._digest(token), 'queued', now, now))
                self.cancels[task_id] = cancel
                self.pool.submit(self._run, task_id, question.strip(), cancel)
        except BaseException:
            with self.lock:
                self.cancels.pop(task_id, None)
            self.slots.release()
            raise
        return dict(task_id=task_id, task_token=token, status='queued')

    @staticmethod
    def _digest(token):
        return hashlib.sha256(str(token).encode()).hexdigest()

    def _authorize(self, db, task_id, token):
        row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if row is None or not hmac.compare_digest(row['token'], self._digest(token)):
            raise PermissionError('task_not_found_or_not_authorized')
        return row

    def get(self, task_id, token, *, after=0, limit=100):
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise ValueError('after must be a nonnegative integer')
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError('limit must be between 1 and 200')
        with self.lock, closing(self._db()) as db:
            row = self._authorize(db, task_id, token)
            rows = db.execute('SELECT seq,payload FROM events WHERE task_id=? AND seq>? ORDER BY seq LIMIT ?', (task_id, after, limit)).fetchall()
            return dict(task_id=task_id, status=row['status'], created=row['created'], updated=row['updated'],
                        events=[dict(seq=r['seq'], event=json.loads(r['payload'])) for r in rows],
                        next_after=rows[-1]['seq'] if rows else after)

    def cancel(self, task_id, token):
        with self.lock, closing(self._db()) as db, db:
            row = self._authorize(db, task_id, token)
            status = row['status']
            if status in {'queued', 'running', 'cancelling'}:
                event = self.cancels.get(task_id)
                if event is not None:
                    event.set()
                status = 'cancelling'
                db.execute('UPDATE tasks SET status=?,updated=? WHERE id=?', (status, time.time(), task_id))
            return dict(task_id=task_id, status=status)

    def _status(self, task_id, status):
        with self.lock, closing(self._db()) as db, db:
            db.execute('UPDATE tasks SET status=?,updated=? WHERE id=?', (status, time.time(), task_id))

    def _event(self, task_id, seq, event):
        with self.lock, closing(self._db()) as db, db:
            db.execute('INSERT INTO events VALUES (?,?,?)', (task_id, seq, json.dumps(event, ensure_ascii=False)))

    def _run(self, task_id, question, cancel):
        seq, done, failed, waiting, limited = 0, False, False, False, False
        stream = None
        final_status = 'failed'
        try:
            self._status(task_id, 'running')
            if cancel.is_set():
                return
            stream = self.runner(task_id, question, cancel)
            for event in stream:
                if cancel.is_set():
                    break
                if not isinstance(event, dict):
                    continue
                seq += 1
                self._event(task_id, seq, event)
                done |= event.get('type') == 'done'
                failed |= event.get('type') == 'error'
                if event.get('type') == 'done':
                    reason = event.get('stop_reason')
                    limited |= reason in {'answer_blocked', 'delivery_incomplete'}
                    failed |= reason not in {None, 'end_turn', 'stop_sequence', 'answer_blocked', 'delivery_incomplete'}
                waiting |= event.get('type') in {'ask_user', 'needs_input', 'awaiting_user_choice'}
            final_status = 'failed' if failed else 'needs_input' if waiting else 'limited' if limited else 'completed' if done else 'failed'
        except Exception:
            # Provider/tool exception text can contain credentials or URLs.
            seq += 1
            self._event(task_id, seq, dict(type='error', message='analysis_task_failed'))
            final_status = 'failed'
        finally:
            try:
                if stream is not None and hasattr(stream, 'close'):
                    stream.close()
            finally:
                self._status(task_id, 'cancelled' if cancel.is_set() else final_status)
                with self.lock:
                    self.cancels.pop(task_id, None)
                self.slots.release()

    def close(self):
        with self.lock:
            self.closed = True
            for cancel in self.cancels.values():
                cancel.set()
        self.pool.shutdown(wait=True)
        if not self._owner_file.closed:
            fcntl.flock(self._owner_file, fcntl.LOCK_UN)
            self._owner_file.close()
