#!/usr/bin/env bash
set -euo pipefail

# Deploy algo-trader to Oracle Cloud ARM instance.
# Usage: ./scripts/deploy-oci.sh [user@host]
#
# Assumes:
#   - SSH key is configured for the target host
#   - Repo is cloned at ~/algo-trader on the remote
#   - .env.oci exists on the remote at ~/algo-trader/.env.oci

REMOTE="${1:-opc@<oracle-vm-ip>}"
REMOTE_DIR="~/algo-trader"
COMPOSE_FILE="docker-compose.oci.yml"

echo "==> Deploying to ${REMOTE}..."

ssh "${REMOTE}" bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
cd ~/algo-trader

echo "--- Pulling latest code..."
git pull --ff-only origin main

# Free disk before building. The build cache previously climbed to
# ~37 GB on the 30 GB root volume and a deploy failed with "no space
# left on device". Pruning >72h-old cache entries here is cheap (a
# fresh deploy has nothing to lose by clearing them) and pre-empts
# that failure mode. Tagged images currently in use stay untouched.
echo "--- Pruning stale docker artifacts..."
docker image prune -f --filter "until=72h" || true
docker builder prune -af --filter "unused-for=72h" || true

echo "--- Building images (native ARM64)..."
# --env-file .env.oci is REQUIRED, not optional: compose interpolates
# ${PUBLIC_API_URL}/${PUBLIC_WS_URL} into the frontend build args, and Next
# bakes NEXT_PUBLIC_* into the client bundle at BUILD time. Without it those
# vars are empty and the bundle falls back to http://localhost:8000, so every
# browser API call (login included) silently hits the user's own machine.
docker compose -f docker-compose.oci.yml --env-file .env.oci build

echo "--- Running database migrations..."
docker compose -f docker-compose.oci.yml --env-file .env.oci run --rm backend alembic upgrade head

echo "--- Starting services..."
docker compose -f docker-compose.oci.yml --env-file .env.oci up -d

echo "--- Pruning old images..."
docker image prune -f

echo "--- Service status:"
docker compose -f docker-compose.oci.yml --env-file .env.oci ps

echo "--- Health check:"
sleep 5
curl -fsS http://localhost:8000/api/health/live && echo " OK" || echo " FAILED"

echo "==> Deploy complete."
REMOTE_SCRIPT
