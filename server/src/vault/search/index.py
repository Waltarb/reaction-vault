"""Vector storage in sqlite-vec. One vec0 table per embedding model, keyed by item id."""
import sqlite3

import numpy as np
import sqlite_vec

from vault.ml.registry import table_name


def ensure_table(db: sqlite3.Connection, key: str, dim: int) -> str:
    table = table_name(key)
    db.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0("
        f"item_id INTEGER PRIMARY KEY, embedding float[{dim}] distance_metric=cosine)"
    )
    db.execute(
        "INSERT INTO embedding_models (key, dim, active) VALUES (?, ?, 1) "
        "ON CONFLICT (key) DO UPDATE SET active = 1",
        (key, dim),
    )
    return table


def blob(vec: np.ndarray) -> bytes:
    return sqlite_vec.serialize_float32(vec.astype(np.float32).tolist())


def upsert(db: sqlite3.Connection, table: str, item_id: int, vec: np.ndarray) -> None:
    db.execute(f"DELETE FROM {table} WHERE item_id = ?", (item_id,))
    db.execute(f"INSERT INTO {table} (item_id, embedding) VALUES (?, ?)", (item_id, blob(vec)))


def get_vec(db: sqlite3.Connection, table: str, item_id: int) -> np.ndarray | None:
    row = db.execute(f"SELECT embedding FROM {table} WHERE item_id = ?", (item_id,)).fetchone()
    return None if row is None else np.frombuffer(row[0], dtype=np.float32)


def nearest(
    db: sqlite3.Connection, table: str, query: np.ndarray, where: list[str], params: list, limit: int,
    exclude_id: int | None = None,
) -> list[tuple[int, float]]:
    """Exact cosine ranking over items passing `where` (aliases: items i). Returns (item_id, similarity).

    A full scan is deliberate: at personal-library scale it takes milliseconds and lets every
    filter compose with ranking without the limits of approximate search.
    """
    clauses = list(where)
    args: list = [blob(query)]
    if exclude_id is not None:
        clauses.append("i.id != ?")
        params = [*params, exclude_id]
    rows = db.execute(
        f"SELECT i.id AS id, vec_distance_cosine(v.embedding, ?) AS d FROM items i "
        f"JOIN {table} v ON v.item_id = i.id WHERE {' AND '.join(clauses)} ORDER BY d LIMIT ?",
        (*args, *params, limit),
    ).fetchall()
    return [(r["id"], 1.0 - r["d"]) for r in rows]


def missing_ids(db: sqlite3.Connection, table: str) -> list[int]:
    return [r[0] for r in db.execute(
        f"SELECT i.id FROM items i LEFT JOIN {table} v ON v.item_id = i.id "
        f"WHERE i.deleted_at IS NULL AND v.item_id IS NULL ORDER BY i.id"
    )]
