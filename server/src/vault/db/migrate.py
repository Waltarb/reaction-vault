import sqlite3
from importlib import resources


def _migrations() -> list[tuple[int, str]]:
    found = []
    for entry in resources.files("vault.db").joinpath("migrations").iterdir():
        if entry.name.endswith(".sql"):
            found.append((int(entry.name.split("_", 1)[0]), entry.read_text(encoding="utf-8")))
    return sorted(found)


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations in order, tracked in PRAGMA user_version. Returns the new version."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, sql in _migrations():
        if version <= current:
            continue
        conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
        current = version
    return current
