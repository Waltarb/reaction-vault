#!/usr/bin/env bash
# One-command Reaction Vault server for a Linux machine with Docker.
#   ./install-server.sh            starts it on http://localhost:8420 and prints a device token
# Data lives in ./data. Re-run any time to update and restart.
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "Docker is required: https://docs.docker.com/engine/install/" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required." >&2; exit 1; }

mkdir -p data
if [ "$(stat -c %u data)" != "1000" ] && [ "$(id -u)" != "1000" ]; then
  echo "Making data/ writable for the container (uid 1000) - may ask for sudo"
  sudo chown 1000:1000 data
fi

# Local use, one machine: bind to loopback only, with tokens required.
cat > docker-compose.local.yml <<'YML'
services:
  vault:
    build: ./server
    restart: unless-stopped
    ports:
      - "127.0.0.1:8420:8420"
    environment:
      VAULT_EMBED_PRECISION: int8
    volumes:
      - ./data:/data
YML

docker compose -f docker-compose.local.yml up -d --build

echo -n "Waiting for the server"
for _ in $(seq 1 60); do
  curl -fs http://127.0.0.1:8420/api/health >/dev/null 2>&1 && break
  echo -n "."; sleep 1
done
echo

if docker compose -f docker-compose.local.yml exec -T vault vault token list 2>/dev/null | grep -q "my-device"; then
  echo "A token named my-device already exists. Create another with:"
  echo "  docker compose -f docker-compose.local.yml exec vault vault token create <name>"
else
  echo "Your device token (shown once, paste it into the app):"
  docker compose -f docker-compose.local.yml exec -T vault vault token create my-device
fi
echo "Server: http://localhost:8420"
