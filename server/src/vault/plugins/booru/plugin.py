"""Safebooru search (the all-ages Gelbooru-style board). Opt-in: set VAULT_BOORU_ENABLED=true.

Queries are tag searches: words are tags, spaces separate tags, use underscores inside a tag
("hatsune_miku smug"). No API key is needed.
"""
import html
import re
from urllib.parse import urlparse

import httpx

from vault.plugins.base import Candidate, SearchPage

API = "https://safebooru.org/index.php"
HOST = "safebooru.org"
MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
        "webp": "image/webp", "webm": "video/webm", "mp4": "video/mp4"}
ID_RE = re.compile(r"^\d{1,12}$")
TAG_RE = re.compile(r"[^\w:()'.!*-]+")


def _https(url: str | None) -> str | None:
    """Accept only safebooru's own https URLs so a bad response can't point the downloader elsewhere."""
    if not url:
        return None
    u = urlparse(url if "://" in url else "https:" + url)
    return u.geturl() if u.scheme == "https" and u.hostname == HOST else None


def parse_post(raw: dict) -> Candidate | None:
    file_url = _https(raw.get("file_url"))
    ext = (file_url or "").rsplit(".", 1)[-1].lower()
    if not (raw.get("id") and file_url and ext in MIME):
        return None
    preview = _https(raw.get("preview_url")) or _https(raw.get("sample_url")) or file_url
    tags = html.unescape(raw.get("tags") or "").split()
    return Candidate(
        source="booru",
        source_id=str(raw["id"]),
        title=" ".join(tags[:4]) or f"safebooru {raw['id']}",
        preview_url=preview,
        file_url=file_url,
        mime=MIME[ext],
        width=raw.get("width") if isinstance(raw.get("width"), int) else None,
        height=raw.get("height") if isinstance(raw.get("height"), int) else None,
        animated=ext in ("gif", "webm", "mp4"),
        page_url=f"https://{HOST}/index.php?page=post&s=view&id={raw['id']}",
        author=raw.get("owner") or None,
        extra={"tags": tags[:30], "rating": raw.get("rating")},
    )


class Booru:
    key = "booru"
    label = "Safebooru"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(10.0), headers={"User-Agent": "reaction-vault/0.1"}
        )

    def _posts(self, tags: str, limit: int, pid: int) -> list[dict]:
        r = self._client.get(API, params={
            "page": "dapi", "s": "post", "q": "index", "json": 1, "tags": tags, "limit": limit, "pid": pid,
        })
        r.raise_for_status()
        return r.json() if r.content.strip() else []  # an empty result is a blank body, not "[]"

    def search(self, query: str, *, animated: bool | None, page: int, limit: int) -> SearchPage:
        words = [TAG_RE.sub("", w) for w in query.split()][:6]
        tags = " ".join(w for w in words if w)
        if animated is True:
            tags += " animated"
        raw = self._posts(tags.strip(), limit, page - 1)
        items = [c for p in raw if (c := parse_post(p)) is not None]
        if animated is False:
            items = [c for c in items if not c.animated]
        return SearchPage(items=items, page=page, has_more=len(raw) >= limit)

    def resolve(self, source_id: str) -> Candidate | None:
        if not ID_RE.match(source_id):
            return None
        raw = self._posts(f"id:{source_id}", 1, 0)
        return parse_post(raw[0]) if raw else None
