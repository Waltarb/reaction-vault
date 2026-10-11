"""Hybrid search: FTS5 keyword hits fused with embedding similarity by reciprocal rank fusion."""
import re
import sqlite3
from functools import lru_cache

import numpy as np

from vault.ml.registry import Embedder, table_name
from vault.search import index

CANDIDATES = 200
RRF_K = 60


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone() is not None


def fts_query(q: str) -> str | None:
    words = re.findall(r"\w+", q.lower())
    return " OR ".join(f'"{w}"*' for w in words[:12]) or None


def fts_ranked(db: sqlite3.Connection, q: str, where: list[str], params: list) -> list[int]:
    match = fts_query(q)
    if match is None:
        return []
    rows = db.execute(
        f"SELECT i.id FROM items_fts f JOIN items i ON i.id = f.rowid "
        f"WHERE items_fts MATCH ? AND {' AND '.join(where)} ORDER BY f.rank LIMIT ?",
        (match, *params, CANDIDATES),
    ).fetchall()
    return [r[0] for r in rows]


@lru_cache(maxsize=256)
def _text_vec(embedder_key: str, q: str, _embedder_id: int, _holder: tuple) -> bytes:
    embedder: Embedder = _holder[0]
    return embedder.embed_texts([q])[0].astype(np.float32).tobytes()


def text_vector(embedder: Embedder, q: str) -> np.ndarray:
    return np.frombuffer(_text_vec(embedder.key, q, id(embedder), (embedder,)), dtype=np.float32)


def search(
    db: sqlite3.Connection, embedder: Embedder | None, q: str, where: list[str], params: list,
    limit: int, offset: int = 0,
) -> tuple[list[tuple[int, float]], bool]:
    """Returns ([(item_id, score)], semantic_used). Scores are fused ranks, higher is better."""
    scores: dict[int, float] = {}
    for rank, item_id in enumerate(fts_ranked(db, q, where, params)):
        scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (RRF_K + rank)
    semantic = False
    if embedder is not None and _table_exists(db, table_name(embedder.key)):
        semantic = True
        qvec = text_vector(embedder, q)
        for rank, (item_id, _sim) in enumerate(
            index.nearest(db, table_name(embedder.key), qvec, where, params, CANDIDATES)
        ):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (RRF_K + rank)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], -kv[0]))
    return ranked[offset : offset + limit], semantic
