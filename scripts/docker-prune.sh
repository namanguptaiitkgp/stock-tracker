#!/usr/bin/env bash
# Host-side Docker cleanup. Run periodically (e.g. weekly cron on OCI host):
#   0 4 * * 0 /home/opc/algo-trader/scripts/docker-prune.sh >> /var/log/docker-prune.log 2>&1
#
# Removes:
#   - dangling images
#   - build cache entries unused for >72h (the main offender; one rebuild
#     leaves multi-GB layers behind)
#   - stopped containers
# Keeps:
#   - tagged images currently in use
#   - named volumes (timescale_data, redis_data — explicit "skip volumes")

set -euo pipefail

echo "=== docker-prune at $(date -Is) ==="
echo "--- before ---"
docker system df

docker image prune -f --filter "until=72h" || true
docker builder prune -af --filter "unused-for=72h" || true
docker container prune -f || true

echo "--- after ---"
docker system df
echo "=== done ==="
