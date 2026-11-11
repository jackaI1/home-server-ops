#!/usr/bin/env bash
# Boot check for the running monitoring stack (used by CI and after a deploy).
# It waits until Prometheus has discovered and scraped every expected job, that the
# backup timestamp has reached Prometheus, and that Grafana reports a healthy database.
# The LifeOS probes only need their scrape to be "up". A failing demo does not fail the boot check.
set -euo pipefail

PROM="${PROM_URL:-http://127.0.0.1:9090}"
GRAFANA="${GRAFANA_URL:-http://127.0.0.1:3000}"
TIMEOUT="${WAIT_SECONDS:-120}"
EXPECTED_JOBS="prometheus node alertmanager blackbox lifeos-demo lifeos-health"
RESULTS=0

pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; RESULTS=1; }

# Prints one line per expected job and returns non-zero until every one is "up".
# shellcheck disable=SC2329  # passed to wait_until by name
report_targets() {
  curl -fsS "$PROM/api/v1/targets?state=active" | python3 -c '
import json, sys
expected = sys.argv[1].split()
targets = json.load(sys.stdin)["data"]["activeTargets"]
seen = {}
for t in targets:
    seen.setdefault(t["labels"]["job"], []).append(t["health"])
ok = True
for job in expected:
    states = seen.get(job, [])
    if states and all(s == "up" for s in states):
        print(f"PASS  target {job} is up ({len(states)})")
    else:
        ok = False
        shown = states or "not discovered"
        print(f"WAIT  target {job} states={shown}")
sys.exit(0 if ok else 1)
' "$EXPECTED_JOBS"
}

# shellcheck disable=SC2329  # passed to wait_until by name
backup_metric_present() {
  curl -fsS "$PROM/api/v1/query?query=home_ops_backup_last_success_timestamp_seconds" | grep -Eq '"result": *\[ *\{'
}

# shellcheck disable=SC2329  # passed to wait_until by name
grafana_database_ok() {
  curl -fsS "$GRAFANA/api/health" | grep -q '"database": *"ok"'
}

wait_until() {  # wait_until <command...>: retry once a second up to WAIT_SECONDS
  local _
  for _ in $(seq 1 "$TIMEOUT"); do
    if "$@" >/tmp/check-last.txt 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}

echo "== prometheus"
if wait_until curl -fsS "$PROM/-/ready"; then pass "prometheus is ready"; else fail "prometheus is not ready"; exit 1; fi

echo "== scrape targets"
if wait_until report_targets; then
  cat /tmp/check-last.txt
else
  cat /tmp/check-last.txt
  fail "not every expected target is up"
fi

echo "== backup timestamp from the textfile collector"
# CI writes a sample file first (see .github/workflows/monitoring.yml).
if wait_until backup_metric_present; then
  pass "backup timestamp metric is visible"
else
  fail "backup timestamp metric is missing"
fi

echo "== Grafana"
if wait_until grafana_database_ok; then
  pass "grafana database is ok"
else
  fail "grafana health check failed"
fi

exit "$RESULTS"
