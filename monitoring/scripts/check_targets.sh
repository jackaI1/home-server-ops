#!/usr/bin/env bash
# Boot check for the running monitoring stack (used by CI and after a deploy).
# It waits for Prometheus, then checks that every scrape target is "up", that the
# backup timestamp reached Prometheus, and that Grafana reports a healthy database.
# The LifeOS probe results are not required to be 1: a failing demo must not fail the boot check.
set -euo pipefail

PROM="${PROM_URL:-http://127.0.0.1:9090}"
GRAFANA="${GRAFANA_URL:-http://127.0.0.1:3000}"
TIMEOUT="${WAIT_SECONDS:-120}"
RESULTS=0

pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; RESULTS=1; }

echo "== waiting for Prometheus"
for _ in $(seq 1 "$TIMEOUT"); do
  curl -fsS "$PROM/-/ready" >/dev/null 2>&1 && break
  sleep 1
done
if curl -fsS "$PROM/-/ready" >/dev/null; then pass "prometheus is ready"; else fail "prometheus is not ready"; exit 1; fi

echo "== scrape targets"
targets="$(curl -fsS "$PROM/api/v1/targets?state=active")"
summary="$(printf '%s' "$targets" | python3 -c '
import json, sys
data = json.load(sys.stdin)["data"]["activeTargets"]
for t in data:
    print(t["labels"]["job"], t["health"], t["scrapeUrl"])
')"
while read -r job health url; do
  [[ -z "$job" ]] && continue
  if [[ "$health" == "up" ]]; then pass "target $job ($url) is up"; else fail "target $job ($url) is $health"; fi
done <<<"$summary"

echo "== backup timestamp from the textfile collector"
# CI writes a sample file first (see .github/workflows/monitoring.yml).
if curl -fsS "$PROM/api/v1/query?query=home_ops_backup_last_success_timestamp_seconds" \
  | grep -q '"status":"success".*"result":\[{'; then
  pass "backup timestamp metric is visible"
else
  fail "backup timestamp metric is missing"
fi

echo "== Grafana"
grafana_ok=0
for _ in $(seq 1 "$TIMEOUT"); do
  if curl -fsS "$GRAFANA/api/health" 2>/dev/null | grep -q '"database": *"ok"'; then grafana_ok=1; break; fi
  sleep 1
done
if [[ "$grafana_ok" == 1 ]]; then pass "grafana database is ok"; else fail "grafana health check failed"; fi

exit "$RESULTS"
