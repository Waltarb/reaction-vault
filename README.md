# Reaction Vault

A self-hosted home for reaction images, GIFs and short webm/mp4 clips. Search by vibe ("smug frog"), find near-duplicates, and send any item as the original, MP4 or GIF.

- **Server** (`server/`): FastAPI + SQLite with [sqlite-vec](https://github.com/asg017/sqlite-vec), content-addressed files on disk, ffmpeg for MP4/GIF, CLIP via ONNX for search and dedupe. Built to run on a ThinkPad X230.
- **Clients** (`clients/`): Kotlin (Android, Windows, Linux). Not started.
- **Discovery**: pluggable sources, starting with 7TV.

Status: scaffold. The server boots, migrates the schema and answers `/api/health`.

## Run it

```bash
docker compose up --build
curl http://localhost:8420/api/health
```

Without Docker (Python 3.12+):

```bash
cd server
pip install -e ".[dev]"
pytest
uvicorn vault.main:app --port 8420
```

Data lives in `./data` (git-ignored): `vault.db`, `blobs/`, `derived/`, `models/`.

## Deploy

`docker-compose.prod.yml` publishes no port and joins your reverse proxy's Docker network (`CADDY_NETWORK` in `.env`). Add the route from `deploy/Caddyfile.snippet`, then:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## License

MIT. See `LICENSE`.
