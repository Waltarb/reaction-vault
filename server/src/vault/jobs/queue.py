"""A small durable job queue in SQLite, drained by one background thread."""
import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

log = logging.getLogger("vault.jobs")

MAX_ATTEMPTS = 3
POLL_SECONDS = 1.0

Handler = Callable[[sqlite3.Connection, sqlite3.Row], None]


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def enqueue(db: sqlite3.Connection, type_: str, item_id: int | None) -> None:
    """Add a job unless an identical one is already waiting."""
    db.execute(
        "INSERT INTO jobs (type, item_id) SELECT ?, ? WHERE NOT EXISTS "
        "(SELECT 1 FROM jobs WHERE type = ? AND item_id IS ? AND status = 'queued')",
        (type_, item_id, type_, item_id),
    )


def recover(db: sqlite3.Connection) -> None:
    """Jobs left 'running' by a crash go back to the queue."""
    db.execute("UPDATE jobs SET status = 'queued' WHERE status = 'running'")


def claim(db: sqlite3.Connection) -> sqlite3.Row | None:
    return db.execute(
        "UPDATE jobs SET status = 'running', attempts = attempts + 1 WHERE id = ("
        "SELECT id FROM jobs WHERE status = 'queued' AND run_after <= ? ORDER BY id LIMIT 1) RETURNING *",
        (_iso(datetime.now(UTC)),),
    ).fetchone()


def finish(db: sqlite3.Connection, job: sqlite3.Row, error: str | None) -> None:
    if error is None:
        db.execute("UPDATE jobs SET status = 'done', error = NULL WHERE id = ?", (job["id"],))
    elif job["attempts"] >= MAX_ATTEMPTS:
        db.execute("UPDATE jobs SET status = 'failed', error = ? WHERE id = ?", (error[:500], job["id"]))
    else:
        retry = _iso(datetime.now(UTC) + timedelta(seconds=30 * job["attempts"]))
        db.execute(
            "UPDATE jobs SET status = 'queued', error = ?, run_after = ? WHERE id = ?",
            (error[:500], retry, job["id"]),
        )


def run_pending(db: sqlite3.Connection, handlers: dict[str, Handler], limit: int = 1000) -> int:
    """Run queued jobs now, in this thread. Returns how many ran. Used by the worker and by tests."""
    ran = 0
    while ran < limit and (job := claim(db)) is not None:
        handler = handlers.get(job["type"])
        try:
            if handler is None:
                raise RuntimeError(f"no handler for job type {job['type']}")
            handler(db, job)
            finish(db, job, None)
        except Exception as e:
            log.exception("job %s (%s) failed", job["id"], job["type"])
            finish(db, job, f"{type(e).__name__}: {e}")
        ran += 1
    return ran


class Worker(threading.Thread):
    def __init__(
        self,
        open_db: Callable[[], sqlite3.Connection],
        handlers: dict[str, Handler],
        on_idle: Callable[[sqlite3.Connection], None] | None = None,
    ):
        super().__init__(name="vault-worker", daemon=True)
        self._open_db, self._handlers, self._on_idle = open_db, handlers, on_idle
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        db = self._open_db()
        try:
            recover(db)
            while not self._stop_event.is_set():
                if run_pending(db, self._handlers, limit=20) == 0:
                    if self._on_idle:
                        try:
                            self._on_idle(db)
                        except Exception:
                            log.exception("idle hook failed")
                    self._stop_event.wait(POLL_SECONDS)
        finally:
            db.close()
