#!/usr/bin/env bash
# Smoke test: send real requests through the Service and check the answers.
# Usage: EXPECT_VERSION=0.2.0 ./smoke.sh   (NS, RELEASE and PORT can be overridden)
# Port-forwards the Service for the duration of the test, then stops the forward.
set -euo pipefail

NS="${NS:-model-serving}"
RELEASE="${RELEASE:-model-server}"
PORT="${PORT:-18080}"
EXPECT_VERSION="${EXPECT_VERSION:?set EXPECT_VERSION to the image tag you deployed}"
forward_pid=""

# shellcheck disable=SC2329  # called by the EXIT trap
cleanup() {
  if [[ -n "$forward_pid" ]]; then kill "$forward_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT

kubectl -n "$NS" port-forward "service/$RELEASE" "$PORT:80" >/tmp/model-server-forward.log 2>&1 &
forward_pid=$!
for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done

base="http://127.0.0.1:$PORT"
curl -fsS "$base/health" >/dev/null
curl -fsS "$base/ready" >/dev/null
echo "PASS  liveness and readiness answer"

reply="$(curl -fsS -X POST "$base/v1/generate" -H 'Content-Type: application/json' \
  -d '{"prompt":"smoke test"}')"
python3 - "$reply" "$EXPECT_VERSION" <<'PY'
import json, sys
body = json.loads(sys.argv[1])
expect = sys.argv[2]
assert body["version"] == expect, f"expected version {expect}, got {body['version']}"
assert body["output"].startswith("stub reply to: smoke test"), body
print(f"PASS  generate answered by version {body['version']}")
PY
