# Deployment runbook

Written for a single Docker host that already runs a Caddy reverse proxy (the ThinkPad X230 running
WaltaDJ). Nothing here is automated; every step is a deliberate command.

## 0. Before you start

- Pick a hostname and point DNS at the host (an A/AAAA record or your DDNS).
- The host's CPU is Ivy Bridge (AVX, no AVX2). `onnxruntime` should dispatch to a supported kernel,
  but this has not been run on that machine. Step 4 checks it before you trust search.
- Disk: the image is about 1.5 GB, the model 155 MB (int8) or 600 MB (fp32).

## 1. Get the code

```bash
git clone https://github.com/Waltarb/reaction-vault ~/reaction-vault
cd ~/reaction-vault
mkdir -p data            # must be owned by uid 1000, which a normal first user is
```

## 2. Configure

Create `.env` next to `docker-compose.prod.yml` (never commit it; it is git-ignored):

```env
CADDY_NETWORK=waltadj_default     # the network the proxy is on: docker network ls
VAULT_EMBED_PRECISION=int8        # fits a 2-core CPU better; fp32 is slightly more accurate
# VAULT_GIPHY_API_KEY=...         # optional
# VAULT_BOORU_ENABLED=true        # optional
```

## 3. Start

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f vault    # wait for "Application startup complete"
```

The model downloads on first start. Until it reports ready (`GET /api/server`, `embeddings.state`),
search is text only and new items are embedded afterwards.

## 4. Check the model runs on this CPU

```bash
docker compose -f docker-compose.prod.yml exec vault python -c \
  "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8420/api/health').read().decode())"
```

Then check `GET /api/server` (through the proxy, with a token): `embeddings.state` should become `ready`. If the process dies with "Illegal instruction", set
`VAULT_EMBED_MODEL=none` (text search only) and open an issue.

## 5. Route it

Append `deploy/Caddyfile.snippet` (hostname changed) to the proxy's Caddyfile, then reload it
without downtime:

```bash
docker exec <caddy-container> caddy reload --config /etc/caddy/Caddyfile
```

## 6. Create device tokens

```bash
docker compose -f docker-compose.prod.yml exec vault vault token create phone
docker compose -f docker-compose.prod.yml exec vault vault token create laptop
```

The token is shown once. Enter it in the client, or on the web UI's sign-in page. Revoke a lost device
with `vault token revoke <name>`. Failed sign-ins are limited to 20 per minute per address.

## 7. Back up and update

- Everything lives in `data/`: stop the container or use `sqlite3 data/vault.db ".backup out.db"`, then copy `data/blobs`.
  `data/derived` and `data/models` can be rebuilt (`vault gc`, `vault reembed`).
- Update: `git pull && docker compose -f docker-compose.prod.yml up -d --build`. Migrations run on start.
- Roll back: check out the previous tag/commit and rebuild. Schema upgrades are forward-only, so restore
  `vault.db` from a backup if you roll back across a schema change.

## 8. Remove

```bash
docker compose -f docker-compose.prod.yml down      # keeps data/
```
