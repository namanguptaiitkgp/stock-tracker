#!/usr/bin/env bash
# Restore a TimescaleDB backup from Cloudflare R2.
#
# DESTRUCTIVE — overwrites the running database. Requires typed confirmation.
#
# Usage:
#   ./scripts/restore-from-r2.sh list                    # show available backups
#   ./scripts/restore-from-r2.sh latest                  # restore newest
#   ./scripts/restore-from-r2.sh key <db-backups/...>    # restore a specific key
#
# Required env (loaded from $ENV_FILE, default /opt/algo-trader/.env.oci):
#   DB_PASSWORD, R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
#   R2_BACKUP_BUCKET
#
# TimescaleDB notes (from CLAUDE.md):
#   - `pg_restore` alone doesn't know about hypertables. The Timescale
#     extension exposes `timescaledb_pre_restore()` / `timescaledb_post_restore()`
#     which this script calls around the actual restore so hypertables come
#     back as hypertables, not flat tables.
#   - The migration history's `post_restore()` failed in the past — see
#     "Known issues" in OCI_DEPLOYMENT_TODO.md. If it fails again, you can
#     finish manually with `SELECT timescaledb_post_restore();` in psql.

set -euo pipefail

# ─── Config ───────────────────────────────────────────────────────────────
ENV_FILE="${ENV_FILE:-/opt/algo-trader/.env.oci}"
DB_CONTAINER="${DB_CONTAINER:-algo-trader-timescaledb-1}"
DB_USER="${DB_USER:-algotrader}"
DB_NAME="${DB_NAME:-algotrader}"
KEY_PREFIX="${KEY_PREFIX:-db-backups}"
AWS_IMAGE="${AWS_IMAGE:-amazon/aws-cli:2.17.0}"

log() { printf '%s restore-from-r2: %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; }
die() { log "FATAL $*"; exit 1; }

# ─── Preflight ────────────────────────────────────────────────────────────
[[ -f "$ENV_FILE" ]] || die "env file not found: $ENV_FILE"
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

for var in DB_PASSWORD R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BACKUP_BUCKET; do
  [[ -n "${!var:-}" ]] || die "required env var $var is empty"
done

command -v docker >/dev/null 2>&1 || die "docker not in PATH"
docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER" || die "container $DB_CONTAINER not running"

R2_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

# Wrapper so the aws-cli `docker run` invocations stay compact below.
aws_r2() {
  docker run --rm \
    -e AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
    -e AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
    "$AWS_IMAGE" \
    "$@" --endpoint-url "$R2_ENDPOINT"
}

# Same wrapper but with -i so stdin streams through (used for `s3 cp - ...`
# downloads). Separated from aws_r2 because adding -i to all calls would
# break non-interactive ones like `s3 ls` running under cron.
aws_r2_stream() {
  docker run --rm -i \
    -e AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
    -e AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
    "$AWS_IMAGE" \
    "$@" --endpoint-url "$R2_ENDPOINT"
}

# ─── Subcommands ──────────────────────────────────────────────────────────
cmd_list() {
  log "listing backups in s3://${R2_BACKUP_BUCKET}/${KEY_PREFIX}/"
  aws_r2 s3 ls "s3://${R2_BACKUP_BUCKET}/${KEY_PREFIX}/" --human-readable
}

resolve_latest_key() {
  # `aws s3 ls` returns lines like:  2026-05-24 07:30:11   234.5 MiB algotrader-2026-05-24T07-30-00Z.dump
  # Lex-sort the prefix (ISO-8601 → lex sort == time sort) and take the last.
  local last_file
  last_file=$(aws_r2 s3 ls "s3://${R2_BACKUP_BUCKET}/${KEY_PREFIX}/" \
    | awk '/algotrader-/ {print $NF}' \
    | sort \
    | tail -n 1)
  [[ -n "$last_file" ]] || die "no backups found in s3://${R2_BACKUP_BUCKET}/${KEY_PREFIX}/"
  printf '%s/%s\n' "$KEY_PREFIX" "$last_file"
}

cmd_restore() {
  local key="$1"
  log "preparing to restore from s3://${R2_BACKUP_BUCKET}/${key}"
  log "TARGET: ${DB_CONTAINER} → database '${DB_NAME}' (user '${DB_USER}')"
  log ""
  log "This will OVERWRITE all data in the live database."
  log "Type the word RESTORE (uppercase) to proceed:"

  read -r confirmation
  if [[ "$confirmation" != "RESTORE" ]]; then
    die "confirmation did not match; aborting"
  fi

  # Pre-restore hook: disables Timescale background workers and tells the
  # extension a restore is incoming. Without this, hypertable chunks won't
  # restore correctly.
  log "calling timescaledb_pre_restore()…"
  docker exec -e PGPASSWORD="$DB_PASSWORD" "$DB_CONTAINER" \
    psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT timescaledb_pre_restore();"

  # Stream the dump from R2 into pg_restore via stdin. --clean drops objects
  # before recreating; --if-exists makes that idempotent. No --create because
  # we're restoring into an existing database (pg_restore --create wants to
  # CREATE DATABASE first, which would conflict with the active connection).
  log "downloading + restoring (this may take several minutes)…"
  set +e
  aws_r2_stream s3 cp "s3://${R2_BACKUP_BUCKET}/${key}" - \
  | docker exec -i -e PGPASSWORD="$DB_PASSWORD" "$DB_CONTAINER" \
      pg_restore -U "$DB_USER" -d "$DB_NAME" \
        --clean --if-exists --no-owner --no-privileges \
        --verbose
  PIPE_STATUS=("${PIPESTATUS[@]}")
  set -e

  # Post-restore must run even if pg_restore reported non-fatal errors — the
  # extension needs to re-enable workers so the live DB is usable again. We
  # report the pg_restore exit code separately.
  log "calling timescaledb_post_restore()…"
  if ! docker exec -e PGPASSWORD="$DB_PASSWORD" "$DB_CONTAINER" \
    psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT timescaledb_post_restore();"; then
    log "WARN timescaledb_post_restore() failed — finish manually:"
    log "     docker exec -it ${DB_CONTAINER} psql -U ${DB_USER} -d ${DB_NAME}"
    log "     algotrader=# SELECT timescaledb_post_restore();"
  fi

  if [[ ${PIPE_STATUS[1]} -ne 0 ]]; then
    log "WARN pg_restore exited ${PIPE_STATUS[1]} (non-zero often just means"
    log "     'role does not exist' or similar benign skips — inspect the log"
    log "     above before treating this as a failure)"
  fi

  log "restore complete from ${key}"
}

# ─── Dispatch ─────────────────────────────────────────────────────────────
case "${1:-}" in
  list)
    cmd_list
    ;;
  latest)
    key=$(resolve_latest_key)
    cmd_restore "$key"
    ;;
  key)
    [[ -n "${2:-}" ]] || die "usage: $0 key <s3-key>"
    cmd_restore "$2"
    ;;
  *)
    cat <<USAGE >&2
Usage: $0 <command>

  list                    show available backups in R2
  latest                  restore the newest backup (with typed confirmation)
  key <s3-key>            restore a specific key (with typed confirmation)

Examples:
  $0 list
  $0 latest
  $0 key db-backups/algotrader-2026-05-24T07-30-00Z.dump
USAGE
    exit 1
    ;;
esac
