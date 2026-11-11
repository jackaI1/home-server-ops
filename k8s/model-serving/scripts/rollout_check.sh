#!/usr/bin/env bash
# Rolling update and rollback check for the model server.
#
#   1. install the good version and smoke test it
#   2. roll to the new version while an in-cluster client sends requests; expect zero failures
#   3. try a version whose image does not exist; the rollout must fail
#   4. the old pods must still answer during the failed rollout
#   5. roll back to the last good revision and smoke test again
#
# Needs helm, kubectl and python3. The images must already be in the cluster (kind load).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART="$HERE/../chart"
NS="${NS:-model-serving}"
RELEASE="${RELEASE:-model-server}"
IMAGE="${IMAGE:-model-server}"
GOOD_TAG="${GOOD_TAG:-0.1.0}"
NEW_TAG="${NEW_TAG:-0.2.0}"
BAD_TAG="${BAD_TAG:-does-not-exist}"
RESULTS=0

pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; RESULTS=1; }

# Runs inside the cluster, using the model image itself, so no extra image is pulled.
load_pod() {  # load_pod <name>
  kubectl -n "$NS" delete pod "$1" --ignore-not-found --wait=true >/dev/null
  kubectl -n "$NS" run "$1" --image="$IMAGE:$NEW_TAG" --image-pull-policy=IfNotPresent \
    --restart=Never --command -- python -c "
import json, time, urllib.request
fails = 0
for i in range(300):
    try:
        req = urllib.request.Request('http://$RELEASE/v1/generate',
            data=json.dumps({'prompt': 'load %d' % i}).encode(),
            headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception as exc:
        fails += 1
        print('request', i, 'failed:', exc, flush=True)
    time.sleep(0.2)
print('failures=%d' % fails)
"
}

smoke() {  # smoke <expected version>
  EXPECT_VERSION="$1" NS="$NS" RELEASE="$RELEASE" "$HERE/smoke.sh"
}

helm_revision() {
  helm list -n "$NS" -o json | python3 -c 'import json, sys; print(json.load(sys.stdin)[0]["revision"])'
}

echo "== 1. install $GOOD_TAG"
helm upgrade --install "$RELEASE" "$CHART" -n "$NS" --create-namespace \
  --set image.repository="$IMAGE" --set image.tag="$GOOD_TAG" --wait --timeout 180s
smoke "$GOOD_TAG"

echo "== 2. roll to $NEW_TAG under load"
load_pod load-during-rollout
sleep 5
helm upgrade "$RELEASE" "$CHART" -n "$NS" --set image.repository="$IMAGE" \
  --set image.tag="$NEW_TAG" --wait --timeout 180s
# The client runs for about 60 seconds; wait for it to finish before reading its log.
kubectl -n "$NS" wait --for=jsonpath='{.status.phase}'=Succeeded pod/load-during-rollout --timeout=300s >/dev/null
logs="$(kubectl -n "$NS" logs load-during-rollout)"
if echo "$logs" | grep -q '^failures=0$'; then
  pass "no requests failed during the rolling update"
else
  fail "requests failed during the rolling update: $(echo "$logs" | tail -5)"
fi
smoke "$NEW_TAG"
good_revision="$(helm_revision)"
echo "    last good revision: $good_revision"

echo "== 3. roll to a broken tag ($BAD_TAG) and expect the rollout to fail"
if helm upgrade "$RELEASE" "$CHART" -n "$NS" --set image.repository="$IMAGE" \
  --set image.tag="$BAD_TAG" --wait --timeout 60s >/dev/null 2>&1; then
  fail "the broken rollout reported success"
else
  pass "the broken rollout failed, as expected"
fi

echo "== 4. the old pods still answer during the failed rollout"
smoke "$NEW_TAG"

echo "== 5. roll back to revision $good_revision"
helm rollback "$RELEASE" "$good_revision" -n "$NS" --wait --timeout 180s
smoke "$NEW_TAG"
image="$(kubectl -n "$NS" get deployment "$RELEASE" -o jsonpath='{.spec.template.spec.containers[0].image}')"
if [[ "$image" == *":$NEW_TAG" ]]; then pass "deployment image is back on $NEW_TAG"; else fail "deployment image is $image"; fi

kubectl -n "$NS" delete pod load-during-rollout --ignore-not-found --wait=false >/dev/null
exit "$RESULTS"
