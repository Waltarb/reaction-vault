# Reaction Vault

A self-hosted home for reaction images, GIFs and short webm/mp4 clips. Search by vibe ("smug frog"), find near-duplicates, and send any item as the original, MP4 or GIF.

- **Server** (`server/`): FastAPI + SQLite with [sqlite-vec](https://github.com/asg017/sqlite-vec), content-addressed files on disk, ffmpeg for MP4/GIF, CLIP via ONNX for search and dedupe. Built to run on a ThinkPad X230.
- **Web UI**: served by the server at `/`. Plain HTML and JS, no build step.
- **Discovery**: pluggable sources, starting with 7TV.
- **Clients** (`clients/`): Kotlin Compose Multiplatform for Windows, Linux and Android. See `clients/README.md`.

## What works

| Area | State |
| --- | --- |
| Ingest | Upload or URL, stage then commit (or `?commit=true`), exact and near-duplicate detection, SSRF-safe URL fetch |
| Library | Items, tags, collections, favorites, soft delete, filters (animated, static, favorites, unsorted, size, transparent) |
| Media | Thumbnails, animated previews, MP4 and GIF renditions built by a background worker |
| Search | FTS5 keyword plus CLIP embedding similarity, fused by rank; "more like this" |
| Auto tags | Zero-shot against a seed vocabulary plus your own tags |
| Sync | Change feed `GET /api/sync?since=<rev>` with tombstones, for offline clients |
| Discover | 7TV, Giphy (`VAULT_GIPHY_API_KEY`) and Safebooru (`VAULT_BOORU_ENABLED=true`) search and save, re-rank results by look against items you pick |
| Auth | Per-device bearer tokens, cookie session for the web UI |

Verified: CI runs the server tests (including ffmpeg conversions) and builds the clients; the Docker image builds and serves; animated WebP ingests; the real CLIP ViT-B/32 (int8) returns sensible search results and tags for 7TV emotes. fp32 and the X230's CPU speed are untested.

## Run it

```bash
docker compose up --build
open http://localhost:8420
```

The first start downloads CLIP ViT-B/32 (about 600 MB at fp32, or about 155 MB with `VAULT_EMBED_PRECISION=int8`) into `data/models/`. Until it is ready, search is text-only and new items are embedded afterwards by the worker.

Without Docker (Python 3.12+, ffmpeg on PATH):

```bash
cd server
pip install -e ".[dev]"
pytest
VAULT_AUTH_DISABLED=true uvicorn vault.main:app --port 8420
```

Data lives in `./data` (git-ignored): `vault.db`, `blobs/`, `derived/`, `models/`, `staging/`.

## Auth

With `VAULT_AUTH_DISABLED` unset, every API and media route needs a device token:

```bash
docker compose exec vault vault token create phone   # printed once, only a hash is stored
docker compose exec vault vault token list
docker compose exec vault vault reembed              # backfill embeddings
```

Clients send `Authorization: Bearer <token>`. The web UI asks for the token once and keeps an HttpOnly cookie.

## Deploy

The container runs as uid 1000, so the host `data/` directory must be writable by it: `mkdir -p data && chown 1000:1000 data` (a normal first user already is uid 1000).

`docker-compose.prod.yml` publishes no port and joins your reverse proxy's Docker network (`CADDY_NETWORK` in `.env`). Add the route from `deploy/Caddyfile.snippet`, then:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

The full step-by-step, including the CPU check for older hardware, is in `deploy/RUNBOOK.md`.

## Configuration

Environment variables, all optional (see `.env.example`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `VAULT_DATA_DIR` | `./data` | Everything the server writes |
| `VAULT_EMBED_MODEL` | `clip-b32` | `none` turns embeddings off |
| `VAULT_EMBED_PRECISION` | `fp32` | `int8` is smaller and faster, slightly less accurate |
| `VAULT_MAX_UPLOAD_BYTES` | 52428800 | Per file |
| `VAULT_NEAR_DUP_COSINE` | 0.96 | Embedding similarity that counts as "looks like one you have" |
| `VAULT_NEAR_DUP_PHASH` | 6 | Perceptual-hash distance that does |
| `VAULT_AUTOTAG_TOP_K` / `VAULT_AUTOTAG_MIN_PROB` | 5 / 0.02 | Auto tag suggestions |
| `VAULT_GIPHY_API_KEY` | empty | Turns the Giphy source on |
| `VAULT_BOORU_ENABLED` | `false` | Turns the Safebooru source on |
| `VAULT_AUTH_DISABLED` | `false` | Development only |

## API sketch

`POST /api/ingest` · `POST /api/ingest/{id}/commit` · `GET /api/items` · `GET /api/search?q=` · `GET /api/items/{id}/similar` · `PATCH /api/items/{id}` · `GET/POST /api/collections` · `GET /api/tags` · `GET /api/sync?since=` · `GET /api/server` · `GET /api/discover/search?q=` · `POST /api/discover/save` · `GET /media/{id}/{original|thumb|preview|send/mp4|send/gif}`. Interactive docs at `/docs`.

## Writing a discovery source

Implement `DiscoverySource` from `server/src/vault/plugins/base.py` (`search` and `resolve`) and register it in `plugins/registry.py`. A source lists candidates and resolves an id to a file URL; the server does the download, so clients never supply URLs to fetch.

## License

MIT. See `LICENSE`.
