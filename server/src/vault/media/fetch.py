import hashlib
import ipaddress
import socket
import uuid
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx

MAX_REDIRECTS = 5


class FetchError(Exception):
    pass


def assert_public(url: str) -> None:
    """Refuse anything that is not http(s) to a globally routable address (no LAN, loopback, metadata)."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("only http(s) URLs are allowed")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as e:
        raise FetchError(f"cannot resolve {parts.hostname}") from e
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise FetchError("URL points at a private or local address")


def download(url: str, staging_dir: Path, max_bytes: int) -> tuple[Path, str, str, str]:
    """Download to the staging dir. Returns (path, sha256, filename, final_url). Redirects re-checked."""
    current = url
    headers = {"User-Agent": "reaction-vault/0.1"}
    with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(15.0, read=30.0)) as client:
        for _ in range(MAX_REDIRECTS + 1):
            assert_public(current)
            with client.stream("GET", current, headers=headers) as r:
                if r.is_redirect:
                    current = urljoin(current, r.headers.get("location", ""))
                    continue
                if r.status_code != 200:
                    raise FetchError(f"remote returned {r.status_code}")
                declared = int(r.headers.get("content-length") or 0)
                if declared > max_bytes:
                    raise FetchError("file is too large")
                dest = staging_dir / f"{uuid.uuid4().hex}.part"
                h, size = hashlib.sha256(), 0
                try:
                    with open(dest, "wb") as out:
                        for chunk in r.iter_bytes(65536):
                            size += len(chunk)
                            if size > max_bytes:
                                raise FetchError("file is too large")
                            h.update(chunk)
                            out.write(chunk)
                except BaseException:
                    dest.unlink(missing_ok=True)
                    raise
                name = unquote(Path(urlparse(current).path).name)
                return dest, h.hexdigest(), name, current
    raise FetchError("too many redirects")
