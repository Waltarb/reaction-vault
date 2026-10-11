"""Discovery plugins find media elsewhere on the web and hand it to the ingest pipeline.

A plugin never writes to the vault. It lists candidates and, given an id it previously returned,
resolves that id to a file URL. The server downloads that URL itself, so clients cannot make it
fetch arbitrary addresses.
"""
from dataclasses import asdict, dataclass, field
from typing import Protocol


@dataclass
class Candidate:
    source: str
    source_id: str
    title: str
    preview_url: str  # small image the client can show directly
    file_url: str  # the file to save
    mime: str
    width: int | None = None
    height: int | None = None
    animated: bool = False
    page_url: str | None = None
    author: str | None = None
    extra: dict = field(default_factory=dict)

    def public(self) -> dict:
        d = asdict(self)
        d.pop("file_url")  # saving goes through source + source_id, never a client-supplied URL
        return d


@dataclass
class SearchPage:
    items: list[Candidate]
    page: int
    has_more: bool
    total: int | None = None


class DiscoverySource(Protocol):
    key: str
    label: str

    def search(self, query: str, *, animated: bool | None, page: int, limit: int) -> SearchPage: ...

    def resolve(self, source_id: str) -> Candidate | None:
        """Fresh details (including file_url) for an id returned by search, or None if gone."""
