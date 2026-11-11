#!/usr/bin/env bash
# Run the operators on a kind cluster and run the end-to-end tests against it.
#
#   scripts/e2e-kind.sh            create a kind cluster called homeops-ops, test, leave it running
#   SKIP_CREATE=1 CLUSTER=ci scripts/e2e-kind.sh   use a cluster that already exists (CI)
#
# What it does: installs cert-manager, applies the GPUJob CRD, gives the node two fake GPUs
# (nvidia.com/gpu capacity, so the batch Jobs can ask for them), starts both controllers as
# background processes it owns, then runs tests/e2e. The controllers are stopped on exit.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER="${CLUSTER:-homeops-ops}"
CERT_MANAGER_URL="${CERT_MANAGER_URL:-https://github.com/cert-manager/cert-manager/releases/download/v1.16.2/cert-manager.yaml}"
PIDS=()

# shellcheck disable=SC2329 # called by the EXIT trap below
stop_controllers() {
  # Only the PIDs this script started. Nothing else is killed.
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
}
trap stop_controllers EXIT

cd "$HERE"
if [ "${SKIP_CREATE:-0}" != 1 ]; then
  kind create cluster --name "$CLUSTER" --wait 120s
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null

echo "== cert-manager"
kubectl apply -f "$CERT_MANAGER_URL"
kubectl -n cert-manager rollout status deployment/cert-manager-webhook --timeout=240s

echo "== namespaces, CRD and fake GPUs"
kubectl create namespace home-apps --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace gpu-jobs --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f crds/gpujob.yaml
kubectl wait --for=condition=Established crd/gpujobs.homeops.local --timeout=60s
NODE="$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')"
kubectl patch node "$NODE" --subresource=status --type=json \
  -p='[{"op":"add","path":"/status/capacity/nvidia.com~1gpu","value":"2"}]'

echo "== controllers"
python3 -m homeops_ops.controller selfheal --manifest examples/services.yaml --interval 3 >selfheal.log 2>&1 &
PIDS+=("$!")
python3 -m homeops_ops.controller gpuqueue --quota examples/quota.yaml --namespace gpu-jobs --interval 3 >gpuqueue.log 2>&1 &
PIDS+=("$!")
echo "started selfheal (pid ${PIDS[0]}) and gpuqueue (pid ${PIDS[1]})"

echo "== end-to-end tests"
set +e
HOMEOPS_E2E=1 python3 -m pytest -q tests/e2e
status=$?
set -e
if [ "$status" -ne 0 ]; then
  echo "== controller logs (tail)"
  tail -n 40 selfheal.log gpuqueue.log || true
  kubectl -n home-apps get deploy,certificate,secret || true
  kubectl -n gpu-jobs get gpujobs,jobs -o wide || true
fi
exit "$status"
