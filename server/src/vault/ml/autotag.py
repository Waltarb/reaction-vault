"""Zero-shot tagging: score an item's embedding against text embeddings of a tag vocabulary."""
import json
import re
import sqlite3
import threading
from importlib import resources
from pathlib import Path

import numpy as np

from vault.ml.registry import Embedder

PROMPT = "a reaction image of {}"
LOGIT_SCALE = 100.0  # CLIP's learned temperature

_cache_lock = threading.Lock()


def seed_vocabulary() -> list[str]:
    text = resources.files("vault.ml").joinpath("vocab/seed_tags.txt").read_text(encoding="utf-8")
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


def vocabulary(db: sqlite3.Connection) -> list[str]:
    """Seed words plus every tag the user has used on a live item."""
    names = dict.fromkeys(t.lower() for t in seed_vocabulary())
    for (n,) in db.execute(
        "SELECT DISTINCT t.name FROM tags t JOIN item_tags it ON it.tag_id = t.id "
        "JOIN items i ON i.id = it.item_id AND i.deleted_at IS NULL WHERE it.origin = 'manual'"
    ):
        names.setdefault(n.lower(), None)
    return list(names)


def _cache_file(model_dir: Path, key: str) -> Path:
    return model_dir / f"vocab-{re.sub(r'[^a-z0-9]+', '_', key)}.json"


def tag_vectors(embedder: Embedder, models_dir: Path, names: list[str]) -> np.ndarray:
    """(len(names), dim) matrix. Text embeddings are cached on disk, so only new tags cost a pass."""
    path = _cache_file(models_dir, embedder.key)
    with _cache_lock:
        cache: dict[str, list[float]] = {}
        if path.exists():
            try:
                cache = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                cache = {}
        todo = [n for n in names if n not in cache]
        if todo:
            for i in range(0, len(todo), 64):
                chunk = todo[i : i + 64]
                vecs = embedder.embed_texts([PROMPT.format(n) for n in chunk])
                for n, v in zip(chunk, vecs):
                    cache[n] = v.round(5).tolist()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache), encoding="utf-8")
        return np.array([cache[n] for n in names], dtype=np.float32)


def suggest(
    embedder: Embedder, models_dir: Path, db: sqlite3.Connection, vec: np.ndarray,
    top_k: int = 5, min_prob: float = 0.02,
) -> dict[str, float]:
    """Best vocabulary matches for an item vector as {tag: probability}, highest first."""
    names = vocabulary(db)
    if not names:
        return {}
    mat = tag_vectors(embedder, models_dir, names)
    logits = LOGIT_SCALE * (mat @ vec)
    logits -= logits.max()
    probs = np.exp(logits)
    probs /= probs.sum()
    order = np.argsort(-probs)[:top_k]
    picked = {names[i]: float(round(probs[i], 4)) for i in order if probs[i] >= min_prob}
    if not picked and len(order):
        picked = {names[order[0]]: float(round(probs[order[0]], 4))}
    return picked
