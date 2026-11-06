import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from automation.domain import Problem, validate_job, validate_key


class Store:
    """One SQLite owner; short transactions serialize claims and fence stale workers."""

    def __init__(self, path, clock=time.time, lease_seconds=20):
        self.path = str(path)
        self.clock = clock
        self.lease_seconds = lease_seconds
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    device TEXT NOT NULL, task TEXT NOT NULL, status TEXT NOT NULL,
                    result TEXT, lease TEXT, expires REAL, attempts INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    event TEXT NOT NULL, at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS queue_order ON jobs(status, created);
                CREATE INDEX IF NOT EXISTS event_job ON events(job_id, seq);
            """)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def ready(self):
        with self.transaction() as db:
            db.execute("SELECT 1 FROM jobs LIMIT 1")

    def event(self, db, job_id, event):
        db.execute(
            "INSERT INTO events(job_id,event,at) VALUES (?,?,?)", (job_id, event, self.clock())
        )

    @staticmethod
    def public(db, row):
        return {
            **{
                k: row[k]
                for k in ("id", "device", "task", "status", "attempts", "created", "updated")
            },
            "result": json.loads(row["result"]) if row["result"] else None,
            "events": [
                dict(event)
                for event in db.execute(
                    "SELECT event,at FROM events WHERE job_id=? ORDER BY seq", (row["id"],)
                )
            ],
        }

    def submit(self, key, payload):
        validate_key(key)
        validate_job(payload)
        with self.transaction() as db:
            old = db.execute("SELECT * FROM jobs WHERE request_key=?", (key,)).fetchone()
            if old:
                if old["device"] != payload["device"] or old["task"] != payload["task"]:
                    raise Problem(409, "Key already used for different work")
                return self.public(db, old)
            if (
                db.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"
                ).fetchone()[0]
                >= 1000
            ):
                raise Problem(429, "Queue is full; try later")
            job_id, now = str(uuid.uuid4()), self.clock()
            db.execute(
                """INSERT INTO jobs(id,request_key,device,task,status,created,updated)
                          VALUES (?,?,?,?,'queued',?,?)""",
                (job_id, key, payload["device"], payload["task"], now, now),
            )
            self.event(db, job_id, "queued")
            return self.public(
                db, db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            )

    def get(self, job_id):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise Problem(404, "Job not found")
            return self.public(db, row)

    def claim(self):
        with self.transaction() as db:
            expired = db.execute(
                "SELECT * FROM jobs WHERE status='running' AND expires<=?", (self.clock(),)
            ).fetchall()
            for row in expired:
                state = "failed" if row["attempts"] >= 3 else "queued"
                result = (
                    json.dumps({"error": "Worker lease expired after three attempts"})
                    if state == "failed"
                    else None
                )
                db.execute(
                    "UPDATE jobs SET status=?,result=?,lease=NULL,expires=NULL,updated=? WHERE id=?",
                    (state, result, self.clock(), row["id"]),
                )
                self.event(db, row["id"], "retry-exhausted" if state == "failed" else "requeued")
            row = db.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created,id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            lease = str(uuid.uuid4())
            db.execute(
                "UPDATE jobs SET status='running',lease=?,expires=?,attempts=attempts+1,updated=? WHERE id=?",
                (lease, self.clock() + self.lease_seconds, self.clock(), row["id"]),
            )
            self.event(db, row["id"], "claimed")
            return {"id": row["id"], "device": row["device"], "task": row["task"], "lease": lease}

    def finish(self, job_id, lease, status, result):
        if status not in ("succeeded", "failed") or not isinstance(result, dict):
            raise Problem(422, "Completion requires succeeded/failed and a result object")
        with self.transaction() as db:
            changed = db.execute(
                """UPDATE jobs SET status=?,result=?,lease=NULL,expires=NULL,updated=?
                WHERE id=? AND status='running' AND lease=? AND expires>?""",
                (status, json.dumps(result), self.clock(), job_id, lease, self.clock()),
            ).rowcount
            if changed != 1:
                raise Problem(409, "Lease is stale or job is no longer running")
            self.event(db, job_id, status)
        return {"status": status}
