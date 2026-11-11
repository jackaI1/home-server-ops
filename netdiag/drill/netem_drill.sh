#!/usr/bin/env bash
# Fault drill: inject packet loss with tc netem and check that netdiag reports it.
#
# Linux only. It needs sudo for tc and tcpdump. The script does this:
#   1. start a local web server that serves a 50 MB file on the loopback interface
#   2. run a baseline download under netdiag capture with no loss; expect exit 0
#   3. add 5% packet loss with tc netem, repeat the download; expect exit 1 and
#      a report that says segments were sent again
#   4. remove the netem rule and stop the web server, even if a step fails
#
# Settings: NETDIAG_IFACE (default lo), NETDIAG_LOSS (default 5%),
# NETDIAG_PORT (default 8765), NETDIAG_DRILL_OUT (keep the captures here).
set -euo pipefail

IFACE="${NETDIAG_IFACE:-lo}"
LOSS="${NETDIAG_LOSS:-5%}"
PORT="${NETDIAG_PORT:-8765}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d)"
OUT="${NETDIAG_DRILL_OUT:-$WORK/out}"
HTTP_PID=""
NETEM_ON=0

cleanup() {
  if [[ "$NETEM_ON" == 1 ]]; then
    sudo -n tc qdisc del dev "$IFACE" root 2>/dev/null || true
  fi
  if [[ -n "$HTTP_PID" ]]; then
    kill "$HTTP_PID" 2>/dev/null || true
    wait "$HTTP_PID" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

mkdir -p "$OUT"
head -c 50000000 /dev/urandom > "$WORK/payload.bin"
(cd "$WORK" && exec python3 -m http.server "$PORT" --bind 127.0.0.1) >/dev/null 2>&1 &
HTTP_PID=$!
curl -sS -o /dev/null --retry 10 --retry-connrefused --retry-delay 1 "http://127.0.0.1:$PORT/payload.bin"

URL="http://127.0.0.1:$PORT/payload.bin"

echo "== Baseline: no injected loss"
set +e
PYTHONPATH="$REPO" python3 -m netdiag run --iface "$IFACE" --out "$OUT/baseline" \
  --filter "tcp port $PORT" --fail-on-issues -- curl -sS -o /dev/null "$URL"
baseline_code=$?
set -e
echo "baseline exit code: $baseline_code"

echo "== Fault: tc netem loss $LOSS on $IFACE"
sudo -n tc qdisc add dev "$IFACE" root netem loss "$LOSS"
NETEM_ON=1
set +e
PYTHONPATH="$REPO" python3 -m netdiag run --iface "$IFACE" --out "$OUT/netem" \
  --filter "tcp port $PORT" --fail-on-issues -- curl -sS -o /dev/null "$URL"
drill_code=$?
set -e
sudo -n tc qdisc del dev "$IFACE" root
NETEM_ON=0

echo "drill exit code: $drill_code"
echo "== Report from the drill"
grep -E "Data segments|Retransmitted|sent again|resent" "$OUT/netem/report.md" || true

if [[ "$baseline_code" -ne 0 ]]; then
  echo "FAIL: the baseline download raised a finding" >&2
  exit 1
fi
if [[ "$drill_code" -ne 1 ]]; then
  echo "FAIL: the injected loss was not reported (exit $drill_code)" >&2
  exit 1
fi
if ! grep -q "were sent again" "$OUT/netem/report.md"; then
  echo "FAIL: the report does not mention retransmissions" >&2
  exit 1
fi
echo "PASS: netem loss was caught in the report"
