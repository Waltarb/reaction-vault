"""Glue between media files, the active embedder and the vector index."""
import logging
from pathlib import Path

import numpy as np

from vault.config import Settings
from vault.media.frames import sample_frames
from vault.ml.registry import Embedder, get_embedder

log = logging.getLogger("vault.ml")


def embed_file(path: Path, kind: str, duration_ms: int | None, embedder: Embedder | None = None) -> np.ndarray | None:
    """One L2-normalised vector for a file: sampled frames embedded then mean-pooled. None if unavailable."""
    embedder = embedder or get_embedder()
    if embedder is None:
        return None
    try:
        frames = sample_frames(path, kind, duration_ms)
        vecs = embedder.embed_images(frames)
    except Exception:
        log.exception("embedding failed for %s", path)
        return None
    mean = vecs.mean(axis=0)
    return (mean / max(float(np.linalg.norm(mean)), 1e-12)).astype(np.float32)


def autotag_params(settings: Settings) -> dict:
    return {"top_k": settings.autotag_top_k, "min_prob": settings.autotag_min_prob}
