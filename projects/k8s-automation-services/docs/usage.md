# Running device checks

## Install and test

I use Python 3.12+, uv, Docker, kind v0.33.0 and kubectl. On macOS, I can install the command-line tools with:

```sh
brew install uv kind kubectl
```

Docker also needs a running engine, such as Docker Desktop or Colima. With Colima installed, `colima start --cpu 2 --memory 4` starts a local VM. I only stop that VM later if I started it for this project and no other work needs it. Linux CI uses the runner's existing Docker engine.

```sh
uv sync --frozen
uv run ruff check .
uv run pytest -q
./scripts/kind-smoke.sh
```

The cluster command downloads Calico v3.33.0, builds the image and loads it into a one-node Kubernetes v1.35.8 cluster. It refuses to reuse an existing cluster with the same name, uses its own temporary kubeconfig and never switches my normal Kubernetes context. It normally cleans up automatically. A failed test exits nonzero and still cleans up.

## Submit a check

I keep a preview only when I want to interact with it:

```sh
./scripts/kind-smoke.sh --keep
export KUBECONFIG=/tmp/device-automation-evidence/kubeconfig
kubectl -n device-automation port-forward service/intake 8080:8080
```

That terminal stays open. In a second terminal:

```sh
export KUBECONFIG=/tmp/device-automation-evidence/kubeconfig
export CLIENT_TOKEN="$(kubectl -n device-automation get secret client-auth -o jsonpath='{.data.token}' | base64 --decode)"
curl --fail-with-body -s http://127.0.0.1:8080/jobs \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: my-first-check' \
  -d '{"device":"lab-switch","task":"link-check"}'
```

The response includes an `id` and starts in `queued` or may already be running. I paste that ID into:

```sh
curl --fail-with-body -s http://127.0.0.1:8080/jobs/PASTE_JOB_ID \
  -H "Authorization: Bearer $CLIENT_TOKEN"
```

Once finished, I see `succeeded`, the model and firmware, two ports marked `up`, an empty `down` list and the events `queued`, `claimed`, `succeeded`. Submitting `lab-switch-faulty` with a new idempotency key returns a `failed` result with `eth1` down. The `inventory` task returns the name, model and firmware without evaluating links.

Allowed device names are `lab-switch` and `lab-switch-faulty`; allowed task names are `inventory` and `link-check`. Requests contain exactly `device` and `task`. The body limit is 16 KiB. Missing authentication returns 401, a wrong token 403, an invalid device or task 422, a reused key with different work 409 and an unavailable audit service 503. A full queue returns 429. `/healthz` and `/readyz` are unauthenticated probe endpoints. There is no public endpoint for claiming or completing jobs.

Port-forwarding is an administrator convenience that bypasses normal pod-to-pod ingress policy. A regular in-cluster caller needs the `app: client` label and the client token. I do not expose a public LoadBalancer or ingress.

## Secrets and rotation

`./scripts/create-secrets.sh` generates independent cryptographically random tokens in temporary files with private permissions, creates four Secrets and removes the files. Existing Secrets are preserved. It never prints token values. The above token lookup is for my interactive shell; I do not paste its output into a file or commit it.

For this disposable cluster, I rotate credentials by deleting the four auth Secrets, rerunning the script and restarting all four deployments so both ends reload them. That briefly interrupts checks. For a real deployment I would use staged rotation and an external secret manager.

## Stop and clean up

I stop the foreground port-forward with Ctrl+C, then run:

```sh
unset CLIENT_TOKEN
kind delete cluster --name device-automation-smoke
docker ps -a --filter label=io.x-k8s.kind.cluster=device-automation-smoke
rm -f /tmp/device-automation-evidence/kubeconfig
unset KUBECONFIG
```

No rows in the filtered Docker output means the owned node is gone. The cluster owns its persistent volume, so deleting the cluster also deletes the history. Its exact PID, start time, mapped API port and cleanup command are in `/tmp/device-automation-evidence/ownership.txt`. Deleting or replacing just the audit pod preserves history; deleting the cluster does not.
