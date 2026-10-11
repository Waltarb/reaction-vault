"""Giphy search. Needs an API key (free at developers.giphy.com), set as VAULT_GIPHY_API_KEY."""
import re

import httpx

from vault.plugins.base import Candidate, SearchPage

API = "https://api.giphy.com/v1/gifs"
ID_RE = re.compile(r"^[A-Za-z0-9]{5,32}$")


def parse_gif(raw: dict) -> Candidate | None:
    images = raw.get("images") or {}
    original = images.get("original") or {}
    preview = images.get("fixed_width_small") or images.get("fixed_width") or original
    if not (raw.get("id") and original.get("url") and preview.get("url")):
        return None
    return Candidate(
        source="giphy",
        source_id=raw["id"],
        title=(raw.get("title") or "").replace(" GIF", "").strip() or raw["id"],
        preview_url=preview["url"],
        file_url=original["url"],
        mime="image/gif",
        width=int(original["width"]) if str(original.get("width", "")).isdigit() else None,
        height=int(original["height"]) if str(original.get("height", "")).isdigit() else None,
        animated=True,
        page_url=raw.get("url"),
        author=raw.get("username") or None,
        extra={"size": int(original["size"]) if str(original.get("size", "")).isdigit() else None},
    )


class Giphy:
    key = "giphy"
    label = "Giphy"

    def __init__(self, api_key: str, rating: str = "pg-13", client: httpx.Client | None = None):
        self._key, self._rating = api_key, rating
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(10.0), headers={"User-Agent": "reaction-vault/0.1"}
        )

    def _get(self, path: str, params: dict) -> dict:
        r = self._client.get(f"{API}/{path}", params={"api_key": self._key, **params})
        r.raise_for_status()
        return r.json()

    def search(self, query: str, *, animated: bool | None, page: int, limit: int) -> SearchPage:
        if animated is False:  # Giphy only has animated results
            return SearchPage(items=[], page=page, has_more=False, total=0)
        body = self._get("search", {
            "q": query, "limit": limit, "offset": (page - 1) * limit, "rating": self._rating, "lang": "en",
        })
        items = [c for raw in body.get("data", []) if (c := parse_gif(raw)) is not None]
        pg = body.get("pagination") or {}
        total = pg.get("total_count")
        return SearchPage(items=items, page=page, has_more=bool(total) and page * limit < total, total=total)

    def resolve(self, source_id: str) -> Candidate | None:
        if not ID_RE.match(source_id):
            return None
        raw = self._get(source_id, {}).get("data")
        return parse_gif(raw) if isinstance(raw, dict) and raw else None
