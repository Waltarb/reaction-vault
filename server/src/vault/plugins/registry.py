from vault.config import get_settings
from vault.plugins.base import DiscoverySource
from vault.plugins.giphy.plugin import Giphy
from vault.plugins.seventv.plugin import SevenTV

_sources: dict[str, DiscoverySource] | None = None


def sources() -> dict[str, DiscoverySource]:
    global _sources
    if _sources is None:
        settings = get_settings()
        found: list[DiscoverySource] = [SevenTV()]
        if settings.giphy_api_key:
            found.append(Giphy(settings.giphy_api_key, settings.giphy_rating))
        _sources = {s.key: s for s in found}
    return _sources


def register(source: DiscoverySource) -> None:
    """Add or replace a source at runtime (used by tests and for custom sources)."""
    sources()[source.key] = source


def reset() -> None:
    global _sources
    _sources = None
