#!/usr/bin/env bash
# End-to-end test of the access point rules in Linux network namespaces. Run as root from the repo root.
#
#   ap    the access point box: dnsmasq (DHCP) and nftables (isolation) run here
#   home  the home network: the sensor endpoint, a laptop that must stay unreachable
#   desk  a client that stands in for an ESP32; a veth pair replaces the Wi-Fi link
#
# hostapd cannot run without a radio, so this test checks its file with the parser instead.
# Values below must match wifi_ap/examples/example.yaml.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-python3}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/wifi-ap-netns.XXXXXX")"
PIDS="$WORK/pids"   # the only processes this script stops are the ones it wrote here
BOUND_LOG="$WORK/bound.log"
: > "$PIDS"
: > "$BOUND_LOG"
export WIFI_AP_PASSPHRASE="${WIFI_AP_PASSPHRASE:-netns-test-passphrase}"
export WIFI_AP_BOUND_LOG="$BOUND_LOG"

SENSOR_IP=192.168.50.10
SENSOR_PORT=8080
LAPTOP_IP=192.168.50.20
DESK_MAC=02:00:00:00:00:01
DESK_IP=10.77.0.50
UNKNOWN_MAC=02:00:00:00:00:99
AP_IP=10.77.0.1

PASS=0
FAIL=0
pass() { PASS=$((PASS + 1)); echo "PASS: $*"; }
fail() { FAIL=$((FAIL + 1)); echo "FAIL: $*" >&2; }
check() { # check "description" command...
  local desc="$1"; shift
  if "$@"; then pass "$desc"; else fail "$desc"; fi
}

cleanup() {
  local status=$?
  while read -r pid; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done < "$PIDS"
  for ns in ap home desk; do
    ip netns del "$ns" 2>/dev/null || true
  done
  rm -rf "$WORK"
  exit "$status"
}
trap cleanup EXIT

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root (sudo)" >&2
  exit 2
fi

echo "== Render the example config"
mkdir -p "$WORK/state"
(cd "$ROOT" && "$PY" -m wifi_ap check wifi_ap/examples/example.yaml)
(cd "$ROOT" && "$PY" -m wifi_ap render wifi_ap/examples/example.yaml --out "$WORK/conf" \
  --state-dir "$WORK/state" --ap-interface wlan-ap --uplink-interface up-ap)
(cd "$ROOT" && "$PY" -m wifi_ap verify "$WORK/conf")
check "dnsmasq accepts the generated config" dnsmasq --test -C "$WORK/conf/dnsmasq.conf"

echo "== Build the namespaces and virtual Ethernet pairs"
for ns in ap home desk; do ip netns add "$ns"; done
ip link add wlan-ap type veth peer name wlan0
ip link set wlan-ap netns ap
ip link set wlan0 netns desk
ip link add up-ap type veth peer name up-home
ip link set up-ap netns ap
ip link set up-home netns home
ip -n ap addr add "$AP_IP/24" dev wlan-ap
ip -n ap addr add 192.168.50.2/24 dev up-ap
ip -n home addr add "$SENSOR_IP/24" dev up-home
ip -n home addr add "$LAPTOP_IP/24" dev up-home
ip -n desk link set wlan0 address "$DESK_MAC"
for ns in ap home desk; do ip -n "$ns" link set lo up; done
ip -n ap link set wlan-ap up
ip -n ap link set up-ap up
ip -n home link set up-home up
ip -n desk link set wlan0 up
ip netns exec ap sysctl -q -w net.ipv4.ip_forward=1

check "nftables accepts the generated ruleset" ip netns exec ap nft -c -f "$WORK/conf/nftables.nft"
ip netns exec ap nft -f "$WORK/conf/nftables.nft"

# Start background processes inside their namespace with nsenter, which execs directly, so $! is the process.
start_stub() { # start_stub NS BIND PORT
  nsenter --net="/run/netns/$1" "$PY" "$ROOT/wifi_ap/netns/sensor_stub.py" serve --bind "$2" --port "$3" \
    >"$WORK/stub-$1-$3.log" 2>&1 &
  echo "$!" >> "$PIDS"
}
echo "== Start the sensor endpoint, a laptop and a port nothing should reach"
start_stub home "$SENSOR_IP" "$SENSOR_PORT"
start_stub home "$LAPTOP_IP" "$SENSOR_PORT"
start_stub home "$SENSOR_IP" 9999
start_stub ap "$AP_IP" 9999
for target in "home $SENSOR_IP $SENSOR_PORT" "home $LAPTOP_IP $SENSOR_PORT"; do
  # shellcheck disable=SC2086  # intentional word splitting of "NS HOST PORT"
  set -- $target
  for _ in $(seq 1 30); do
    if ip netns exec "$1" "$PY" "$ROOT/wifi_ap/netns/sensor_stub.py" probe "$2" "$3" --timeout 1 >/dev/null 2>&1; then
      break
    fi
    sleep 0.2
  done
done

echo "== Start dnsmasq in the ap namespace"
ip netns exec ap dnsmasq -C "$WORK/conf/dnsmasq.conf" --log-facility="$WORK/dnsmasq.log"
for _ in $(seq 1 25); do [[ -s "$WORK/state/dnsmasq.pid" ]] && break; sleep 0.2; done
DNSMASQ_PID="$(cat "$WORK/state/dnsmasq.pid")"
echo "$DNSMASQ_PID" >> "$PIDS"

dhcp_as_desk() { # one DHCP attempt from the desk client, bounded by timeout
  ip netns exec desk timeout 25 dhclient -1 -v -sf "$ROOT/wifi_ap/netns/apply_lease.sh" \
    -pf "$WORK/dhclient.pid" -lf "$WORK/dhclient.leases" wlan0 >>"$WORK/dhclient.log" 2>&1 || true
}
probe_from() { # probe_from NS HOST PORT -> prints outcome, exit code from probe
  ip netns exec "$1" "$PY" "$ROOT/wifi_ap/netns/sensor_stub.py" probe "$2" "$3" --timeout 3
}

echo "== Known device gets its static lease"
dhcp_as_desk
check "desk-node received 10.77.0.50 over DHCP" grep -qx "$DESK_IP" "$BOUND_LOG"
check "desk-node has the leased address on wlan0" \
  bash -c "ip -n desk -4 addr show dev wlan0 | grep -q '$DESK_IP/24'"

echo "== Devices can reach the sensor endpoint"
check "sensor endpoint answers on the allowed port" \
  bash -c "[[ \"\$(ip netns exec desk $PY $ROOT/wifi_ap/netns/sensor_stub.py probe $SENSOR_IP $SENSOR_PORT --timeout 5)\" == ok ]]"

echo "== Everything else on the home network is dropped"
for target in "$SENSOR_IP 9999" "$LAPTOP_IP $SENSOR_PORT" "$AP_IP 9999"; do
  # shellcheck disable=SC2086  # intentional word splitting of "HOST PORT"
  set -- $target
  outcome="$(probe_from desk "$1" "$2" || true)"
  if [[ "$outcome" == "timeout" ]]; then
    pass "dropped silently: $1:$2 (probe said $outcome)"
  else
    fail "expected a silent drop for $1:$2, probe said '$outcome'"
  fi
done

echo "== A device that is not on the list gets no lease"
before="$(wc -l < "$BOUND_LOG")"
ip -n desk link set wlan0 address "$UNKNOWN_MAC"
ip -n desk addr flush dev wlan0
dhcp_as_desk
after="$(wc -l < "$BOUND_LOG")"
check "unknown MAC gets no lease" test "$before" -eq "$after"

if [[ "$FAIL" -gt 0 ]]; then
  # Show only the last lines of each log, so a failure is readable without a flood of output.
  echo "== Diagnostics (last lines only)"
  for log in "$WORK/dnsmasq.log" "$WORK/dhclient.log"; do
    if [[ -f "$log" ]]; then echo "--- $(basename "$log")"; tail -n 40 "$log"; fi
  done
  echo "--- addresses"
  ip -n ap -brief addr 2>/dev/null || true
  ip -n desk -brief addr 2>/dev/null || true
  echo "--- firewall rules in ap"
  ip netns exec ap nft list ruleset 2>/dev/null | head -n 40 || true
fi

echo
echo "== Result: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
