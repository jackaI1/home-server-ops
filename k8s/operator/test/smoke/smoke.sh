#!/usr/bin/env bash
# Smoke test against a running cluster that has the operator installed (see the chart).
#
# 1. apply a ServiceApp and wait for the rollout and a passing HealthCheck
# 2. bump the version and check that the Deployment runs the new image
# 3. break the health path and check that HealthCheck becomes False
# 4. restore the health path and check that HealthCheck becomes True again
# 5. delete the ServiceApp and check that its Deployment is removed
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS="${SMOKE_NAMESPACE:-default}"
NAME=smoke
TIMEOUT="${SMOKE_TIMEOUT:-300s}"

kc() { kubectl -n "$NS" "$@"; }

cleanup() {
  kc delete serviceapp "$NAME" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT

condition() {
  kc get serviceapp "$NAME" -o jsonpath="{.status.conditions[?(@.type==\"$1\")].status}"
}

wait_condition() {
  # $1 = condition type, $2 = expected status
  local deadline=$((SECONDS + 300))
  until [[ "$(condition "$1")" == "$2" ]]; do
    if (( SECONDS > deadline )); then
      echo "FAIL: condition $1 never became $2 (now: $(condition "$1"))" >&2
      kc describe serviceapp "$NAME" | tail -20 >&2 || true
      exit 1
    fi
    sleep 3
  done
  echo "ok: $1=$2"
}

image_now() {
  kc get deployment "$NAME" -o jsonpath='{.spec.template.spec.containers[0].image}'
}

echo "== 1. create the ServiceApp"
kc apply -f "$HERE/serviceapp-v1.yaml"
wait_condition HealthCheck True
kc rollout status deployment/"$NAME" --timeout="$TIMEOUT"
wait_condition Ready True
image="$(image_now)"
[[ "$image" == "nginx:1.27-alpine" ]] || { echo "FAIL: image is $image" >&2; exit 1; }
echo "ok: deployment runs $image"

echo "== 2. bump the version"
kc patch serviceapp "$NAME" --type merge -p '{"spec":{"version":"1.28-alpine"}}'
kc rollout status deployment/"$NAME" --timeout="$TIMEOUT"
wait_condition Ready True
image="$(image_now)"
[[ "$image" == "nginx:1.28-alpine" ]] || { echo "FAIL: image is $image after the bump" >&2; exit 1; }
deployed="$(kc get serviceapp "$NAME" -o jsonpath='{.status.deployedVersion}')"
[[ "$deployed" == "1.28-alpine" ]] || { echo "FAIL: deployedVersion is $deployed" >&2; exit 1; }
echo "ok: deployment runs $image"

echo "== 3. break the health path"
kc patch serviceapp "$NAME" --type merge -p '{"spec":{"healthPath":"/does-not-exist"}}'
wait_condition HealthCheck False
reason="$(kc get serviceapp "$NAME" -o jsonpath='{.status.conditions[?(@.type=="HealthCheck")].reason}')"
[[ "$reason" == "HealthCheckFailed" ]] || { echo "FAIL: reason is $reason" >&2; exit 1; }
echo "ok: HealthCheck reason is $reason"

echo "== 4. restore the health path"
kc patch serviceapp "$NAME" --type merge -p '{"spec":{"healthPath":"/"}}'
wait_condition HealthCheck True
kc rollout status deployment/"$NAME" --timeout="$TIMEOUT"

echo "== 5. delete the ServiceApp and check its Deployment is removed"
kc delete serviceapp "$NAME" --wait=true
# The garbage collector removes owned objects after the ServiceApp is gone, so poll.
deadline=$((SECONDS + 120))
until ! kc get deployment "$NAME" >/dev/null 2>&1; do
  if (( SECONDS > deadline )); then
    echo "FAIL: deployment $NAME still exists 120s after the ServiceApp was deleted" >&2
    exit 1
  fi
  sleep 2
done
echo "ok: deployment removed by owner reference"
echo "PASS: ServiceApp smoke test"
