#!/usr/bin/env bash
# Idempotent host setup for the OCI Always-Free VM.
#
# Two host-level concerns this manages, both gating on staying under
# the OCI Free tier reclamation/cost thresholds:
#
# 1. Idle-keepalive cron. OCI reclaims Always-Free A1 instances if
#    CPU+memory+network are all <20% (95th percentile) for 7 days.
#    Memory on this VM sits at ~20% (right at the threshold), so a
#    minute-level tiny outbound HTTPS hit keeps network non-zero and
#    the CPU bumped, guaranteeing we never trip the reclaim timer.
#
# 2. Weekly docker prune. The build cache regrows after every deploy
#    and previously climbed to 37 GB on the 30 GB root volume — the
#    last deploy failed with "no space left on device" until manually
#    pruned. scripts/docker-prune.sh already exists; this just wires
#    it into the host crontab.
#
# Usage on the VM:
#   bash ~/algo-trader/scripts/oci-host-setup.sh
#
# Idempotent — running it again after the cron is already installed
# is a no-op. Edit the marker tags below if you change a cron line.

set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/algo-trader}"
PRUNE_SCRIPT="${REPO_DIR}/scripts/docker-prune.sh"

# Lines to install, each tagged with a unique marker so we can detect
# whether they're already in the crontab.
declare -A CRON_LINES
CRON_LINES["oci-keepalive"]='* * * * * curl -fsS -o /dev/null --max-time 8 https://www.google.com/generate_204 # oci-keepalive'
CRON_LINES["oci-docker-prune"]="0 4 * * 0 ${PRUNE_SCRIPT} >> /var/log/docker-prune.log 2>&1 # oci-docker-prune"

# Read the current crontab (empty if none).
existing="$(crontab -l 2>/dev/null || true)"
new="$existing"

for marker in "${!CRON_LINES[@]}"; do
    line="${CRON_LINES[$marker]}"
    if printf '%s\n' "$existing" | grep -q "# $marker$"; then
        echo "  cron present: $marker"
    else
        echo "  cron adding:  $marker"
        new="$(printf '%s\n%s\n' "$new" "$line")"
    fi
done

# Strip leading blank lines that printf may have inserted.
new="$(printf '%s\n' "$new" | sed '/./,$!d')"

if [[ "$new" != "$existing" ]]; then
    printf '%s\n' "$new" | crontab -
    echo "host crontab updated."
else
    echo "host crontab already up to date."
fi

# Ensure the log file is writable by opc (the prune cron writes to it).
if [[ ! -e /var/log/docker-prune.log ]]; then
    sudo touch /var/log/docker-prune.log
    sudo chown "$(id -un)" /var/log/docker-prune.log
fi

echo
echo "current crontab:"
crontab -l
