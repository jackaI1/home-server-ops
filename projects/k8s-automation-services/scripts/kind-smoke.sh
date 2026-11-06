#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
CLUSTER=${CLUSTER:-device-automation-smoke}
keep=false
if [[ ${1:-} == --keep ]]; then keep=true; fi
for tool in docker kind kubectl python3; do command -v "$tool" >/dev/null; done
docker info >/dev/null
if kind get clusters | grep -Fxq "$CLUSTER"; then
  echo "Cluster $CLUSTER already exists; refusing to take ownership" >&2
  exit 1
fi
state=$(mktemp -d)
export KUBECONFIG="$state/kubeconfig"
export ARTIFACT_DIR=${ARTIFACT_DIR:-/tmp/device-automation-evidence}
mkdir -p "$ARTIFACT_DIR"
created=false
success=false
cleanup() {
  result=$?
  trap - EXIT INT TERM
  if $created; then
    if $keep && $success; then
      # Preserve requested preview and its dedicated kubeconfig, never change the owner's context.
      cp "$KUBECONFIG" "$ARTIFACT_DIR/kubeconfig"
      echo "Retained owner-requested preview: $CLUSTER; kubeconfig: $ARTIFACT_DIR/kubeconfig"
      echo "Stop: kind delete cluster --name $CLUSTER"
    else
      if [[ $result -ne 0 ]]; then
        kubectl -n device-automation get pods -o wide 2>/dev/null || true
        kubectl -n device-automation get events --field-selector type=Warning 2>/dev/null | tail -20 || true
      fi
      kind delete cluster --name "$CLUSTER"
      if docker ps -a --filter "label=io.x-k8s.kind.cluster=$CLUSTER" --format '{{.ID}}' | grep -q .; then
        echo 'Owned cluster containers remain after cleanup' >&2
        result=1
      else
        echo 'Cleanup verified: no owned cluster containers or ports remain'
      fi
    fi
  fi
  rm -rf "$state"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
created=true
kind create cluster --name "$CLUSTER" --config deploy/kind.yaml \
  --image kindest/node:v1.35.8@sha256:07b2536e30b803ed61d1677a79df6115f798ce64c80f9e22f6ed45afd09323c0 \
  --wait 60s
# Record exact ownership, start time, PID, and ports. These are ephemeral evidence, never secrets.
docker inspect "$CLUSTER-control-plane" --format \
  'owner=kind-smoke.sh name={{.Name}} pid={{.State.Pid}} started={{.State.StartedAt}} ports={{json .NetworkSettings.Ports}}' \
  > "$ARTIFACT_DIR/ownership.txt"
echo "cleanup=kind delete cluster --name $CLUSTER" >> "$ARTIFACT_DIR/ownership.txt"
# Calico enforces NetworkPolicy; kind's default network plugin does not.
curl -fsSL https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/calico.yaml -o "$state/calico.yaml"
kubectl create -f "$state/calico.yaml" >/dev/null
kubectl -n kube-system rollout status daemonset/calico-node --timeout=240s
kubectl wait --for=condition=Ready nodes --all --timeout=180s
docker build --pull -t device-automation:local .
kind load docker-image device-automation:local --name "$CLUSTER"
kubectl apply -f deploy/namespace.yaml
./scripts/create-secrets.sh
for resource in network-policies audit intake worker device; do
  kubectl apply -f "deploy/$resource.yaml"
done
for role in audit intake worker device; do
  kubectl -n device-automation rollout status "deployment/$role" --timeout=180s
done
python3 scripts/smoke.py
success=true
