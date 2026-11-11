#!/usr/bin/env bash
# Create the accounts and the per-user GPU limit in the Slurm accounting database.
# Run once on the controller after slurmdbd is up. Re-running is safe: existing entries are skipped.
#
# Limits: a user may hold at most MAX_GPUS_PER_USER GPUs at once in each partition (MaxTRESPerUser).
set -euo pipefail

MAX_GPUS_PER_USER="${MAX_GPUS_PER_USER:-2}"
USERS="${USERS:-}"   # space-separated login names, for example: USERS="alice bob"
[ -n "$USERS" ] || { echo "set USERS to the login names to add" >&2; exit 2; }

sacctmgr -i add account homelab Description="home GPU queue" Organization=home 2>/dev/null || true
sacctmgr -i add qos bench Priority=10 MaxTRESPerUser=gres/gpu="$MAX_GPUS_PER_USER" 2>/dev/null || true
sacctmgr -i add qos review Priority=100 2>/dev/null || true

for user in $USERS; do
  sacctmgr -i add user "$user" account=homelab 2>/dev/null || true
done
sacctmgr show assoc format=User,Account,QOS,MaxTRESPerUser -p
