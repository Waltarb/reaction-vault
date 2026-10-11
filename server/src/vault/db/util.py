import sqlite3
from contextlib import contextmanager


@contextmanager
def tx(db: sqlite3.Connection):
    """Write transaction. The connection is in autocommit mode, so BEGIN/COMMIT are explicit."""
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")


def bump_rev(db: sqlite3.Connection) -> int:
    """Advance the global change counter. Call inside tx() and stamp the changed rows with it."""
    db.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'rev'")
    return int(db.execute("SELECT value FROM meta WHERE key = 'rev'").fetchone()[0])


def current_rev(db: sqlite3.Connection) -> int:
    return int(db.execute("SELECT value FROM meta WHERE key = 'rev'").fetchone()[0])
