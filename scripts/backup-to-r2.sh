#!/usr/bin/env bash
# Stream a full TimescaleDB dump to Cloudflare R2.
#
# Designed to run from cron on the OCI host. Pipes pg_dump's stdout straight
# through aws-cli (in a one-shot Docker container) into R2 — no intermediate
# file on disk. R2's S3-compatible API accepts streaming uploads via stdin.
#
# Required env (loaded from $ENV_FILE, default /opt/algo-trader/.env.oci):
#   DB_PASSWORD              # already present for the running stack
#   R2_ACCOUNT_ID            # 32-hex-char Cloudflare account ID
#   R2_ACCESS_KEY_ID         # R2 S3-compat Access Key
#   R2_SECRET_ACCESS_KEY     # R2 S3-compat Secret
#   R2_BACKUP_BUCKET         # bucket name you created in the R2 dashboard
#
# Exit codes:
#   0 success
#   1 missing config / preflight failure
#   2 pg_dump failed (no upload attempted)
#   3 upload failed (dump succeeded but didn't land in R2)
#
# Smoke test (run manually before cron'ing):
#   ENV_FILE=~/algo-trader/.env.oci ./scripts/backup-to-r2.sh
#
# Companion: scripts/restore-from-r2.sh

set -euo pipefail

# ─── Config ───────────────────────────────────────────────────────────────
ENV_FILE="${ENV_FILE:-/opt/algo-trader/.env.oci}"
DB_CONTAINER="${DB_CONTAINER:-algo-trader-timescaledb-1}"
DB_USER="${DB_USER:-algotrader}"
DB_NAME="${DB_NAME:-algotrader}"
KEY_PREFIX="${KEY_PREFIX:-db-backups}"
AWS_IMAGE="${AWS_IMAGE:-amazon/aws-cli:2.17.0}"

# Log to stderr with an ISO-8601 timestamp so cron emails / journalctl are
# greppable. Stdout is reserved for structured success output (one JSON line)
# so a downstream alerting pipeline can parse it later if needed.
log() { printf '%s backup-to-r2: %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; }

# ─── Preflight ────────────────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
  log "FATAL env file not found: $ENV_FILE (set ENV_FILE=... to override)"
  exit 1
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

for var in DB_PASSWORD R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BACKUP_BUCKET; do
  if [[ -z "${!var:-}" ]]; then
    log "FATAL required env var $var is empty (check $ENV_FILE)"
    exit 1
  fi
done

if ! command -v docker >/dev/null 2>&1; then
  log "FATAL docker not in PATH"
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  log "FATAL container $DB_CONTAINER not running (docker ps shows nothing matching)"
  exit 1
fi

R2_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
TIMESTAMP=$(date -u +'%Y-%m-%dT%H-%M-%SZ')
KEY="${KEY_PREFIX}/algotrader-${TIMESTAMP}.dump"
S3_URI="s3://${R2_BACKUP_BUCKET}/${KEY}"

log "starting backup → ${S3_URI}"

# ─── Dump → stream → upload ───────────────────────────────────────────────
# pg_dump runs inside the timescaledb container. -Fc = custom format, binary,
# zlib-compressed at level 6 by default. Streamed via stdout, never written
# to local disk inside the container.
#
# aws-cli runs as a one-shot Docker container. -i keeps stdin open so the
# pg_dump stream becomes the upload payload. `s3 cp - s3://...` reads the
# whole stdin and multiparts to R2 (8MB parts by default).
#
# `set -o pipefail` (from `set -euo pipefail` above) makes the pipeline fail
# if pg_dump fails even if aws-cli succeeds with an empty body. The two
# distinct exit codes (2 / 3) come from PIPESTATUS inspection below.

set +e
docker exec \
  -e PGPASSWORD="$DB_PASSWORD" \
  "$DB_CONTAINER" \
  pg_dump -Fc -U "$DB_USER" -d "$DB_NAME" --no-owner --no-privileges \
| docker run --rm -i \
    -e AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
    -e AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
    "$AWS_IMAGE" \
    s3 cp - "$S3_URI" \
      --endpoint-url "$R2_ENDPOINT" \
      --expected-size 1073741824 \
      --no-progress
PIPE_STATUS=("${PIPESTATUS[@]}")
set -e

DUMP_EXIT=${PIPE_STATUS[0]}
UPLOAD_EXIT=${PIPE_STATUS[1]}

if [[ $DUMP_EXIT -ne 0 ]]; then
  log "FATAL pg_dump exited $DUMP_EXIT"
  exit 2
fi

if [[ $UPLOAD_EXIT -ne 0 ]]; then
  log "FATAL aws s3 cp exited $UPLOAD_EXIT (dump succeeded but upload failed)"
  exit 3
fi

# ─── Verify object exists + capture size for the success log line ─────────
SIZE=$(docker run --rm \
  -e AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
  -e AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
  "$AWS_IMAGE" \
  s3api head-object \
    --bucket "$R2_BACKUP_BUCKET" \
    --key "$KEY" \
    --endpoint-url "$R2_ENDPOINT" \
    --query 'ContentLength' \
    --output text 2>/dev/null || echo "0")

log "uploaded ${SIZE} bytes to ${S3_URI}"

# One-line JSON success record on stdout for downstream parsing.
printf '{"event":"backup_complete","key":"%s","bytes":%s,"timestamp":"%s"}\n' \
  "$KEY" "$SIZE" "$TIMESTAMP"
