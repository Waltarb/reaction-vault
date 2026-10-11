"""7TV emotes via the public GraphQL API (https://7tv.io/v3/gql) and the cdn.7tv.app CDN."""
import re

import httpx

from vault.plugins.base import Candidate, SearchPage

GQL_URL = "https://7tv.io/v3/gql"
SITE = "https://7tv.app/emotes/"
ID_RE = re.compile(r"^[0-9A-Z]{26}$")

_FILES = "name format width height frame_count size"
SEARCH = (
    "query($q:String!,$p:Int,$l:Int,$f:EmoteSearchFilter){emotes(query:$q,page:$p,limit:$l,filter:$f)"
    "{count items{id name animated owner{username} host{url files{" + _FILES + "}}}}}"
)
ONE = "query($id:ObjectID!){emote(id:$id){id name animated owner{username} host{url files{" + _FILES + "}}}}"

MIME = {"WEBP": "image/webp", "GIF": "image/gif", "AVIF": "image/avif", "PNG": "image/png"}


def _pick(files: list[dict], formats: tuple[str, ...]) -> dict | None:
    """Largest file in the first available format of `formats` (names like '4x.webp')."""
    for fmt in formats:
        matching = [f for f in files if f.get("format") == fmt]
        if matching:
            return max(matching, key=lambda f: (f.get("width") or 0, f.get("size") or 0))
    return None


def parse_emote(raw: dict) -> Candidate | None:
    host = raw.get("host") or {}
    files = host.get("files") or []
    base = host.get("url") or ""
    if base.startswith("//"):
        base = "https:" + base
    # WebP keeps alpha and is the smallest; GIF is the fallback some emotes still need.
    best = _pick(files, ("WEBP", "GIF", "PNG"))
    thumb = min(
        (f for f in files if f.get("format") == (best or {}).get("format")),
        key=lambda f: abs((f.get("width") or 0) - 64),
        default=None,
    )
    if not (raw.get("id") and base and best and thumb):
        return None
    return Candidate(
        source="7tv",
        source_id=raw["id"],
        title=raw.get("name") or raw["id"],
        preview_url=f"{base}/{thumb['name']}",
        file_url=f"{base}/{best['name']}",
        mime=MIME.get(best["format"], "application/octet-stream"),
        width=best.get("width"),
        height=best.get("height"),
        animated=bool(raw.get("animated")) or (best.get("frame_count") or 1) > 1,
        page_url=SITE + raw["id"],
        author=((raw.get("owner") or {}).get("username")),
        extra={"size": best.get("size"), "frames": best.get("frame_count")},
    )


class SevenTV:
    key = "7tv"
    label = "7TV"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(10.0), headers={"User-Agent": "reaction-vault/0.1"}
        )

    def _gql(self, query: str, variables: dict) -> dict:
        r = self._client.post(GQL_URL, json={"query": query, "variables": variables})
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            raise RuntimeError(f"7TV error: {body['errors'][0].get('message', 'unknown')}")
        return body["data"]

    def search(self, query: str, *, animated: bool | None, page: int, limit: int) -> SearchPage:
        flt = {"exact_match": False, "case_sensitive": False, "ignore_tags": False}
        if animated:
            flt["animated"] = True
        data = self._gql(SEARCH, {"q": query, "p": page, "l": limit, "f": flt})["emotes"]
        items = [c for raw in data["items"] if (c := parse_emote(raw)) is not None]
        if animated is False:
            items = [c for c in items if not c.animated]
        total = data.get("count")
        return SearchPage(items=items, page=page, has_more=bool(total) and page * limit < total, total=total)

    def resolve(self, source_id: str) -> Candidate | None:
        if not ID_RE.match(source_id):
            return None
        raw = self._gql(ONE, {"id": source_id}).get("emote")
        return parse_emote(raw) if raw else None
