# Kubernetes operator notes

Two small controllers live in `k8s/operators`. A controller is a loop that reads what you declared,
looks at what is actually running, and changes the cluster until they match. Both controllers are
written in Python with the official `kubernetes` client. They run as a loop that repeats every few
seconds, and each pass is safe to repeat.

## selfheal: declared services come back by themselves

`examples/services.yaml` lists the services the home cluster should run. For each one, selfheal makes sure
four objects exist and match the manifest:

- a `Deployment` with the image, replica count and port
- a `Service` in front of it
- a cert-manager `Issuer` that signs with its own key (self-signed)
- a cert-manager `Certificate` for the service's host name. cert-manager turns it into a TLS
  `Secret`, and renews it.

If one of these is deleted, the next pass creates it again. If one is changed by hand (a replica
count, an image tag), the next pass puts the manifest's value back. Fields that Kubernetes fills in
for itself, such as `status` or `clusterIP`, are ignored, so a healthy object is never touched.

What it does not do: it does not delete a service that you remove from the manifest. Removing a
service stays a manual step, so a typo in the file cannot wipe out a running app.

```sh
python -m homeops_ops.controller selfheal --manifest examples/services.yaml --interval 10
```

## gpuqueue: GPU jobs wait for quota and free GPUs

A `GPUJob` object says which team it is for, how many GPUs it needs, and which image runs it.
`crds/gpujob.yaml` defines the object. The controller admits a job only when two limits have room:

1. the team's quota in `examples/quota.yaml` (how many GPUs the team may hold at once)
2. the GPUs free in the whole cluster (`clusterGPUs`)

Jobs are admitted by priority first, then by age. A job that does not fit stays `Queued`, and its
status says why (`TeamQuota` or `NoFreeGPUs`) and where it is in line. An admitted job becomes a
batch `Job` that asks Kubernetes for the GPUs. When the batch Job succeeds or fails, the GPUJob's
status changes and its GPUs go back to the queue in the same pass.

A finalizer (`homeops.local/gpujob-cleanup`) is added to every GPUJob. When someone deletes a running
job, the controller first deletes its batch Job, and only then removes the finalizer, so the object
is not gone while its work is still running.

```sh
kubectl apply -f crds/gpujob.yaml
kubectl create namespace gpu-jobs
python -m homeops_ops.controller gpuqueue --quota examples/quota.yaml --namespace gpu-jobs --interval 5
kubectl -n gpu-jobs get gpujobs
```

## Tests

- `python -m pytest -q tests` runs the reconciliation tests. They use an in-memory fake of the
  cluster (`tests/fake_kube.py`), so no cluster is needed. The tests cover drift, deleted objects,
  quota and capacity ordering, finalizers and failed runs.
- `scripts/e2e-kind.sh` creates a kind cluster, installs cert-manager, applies the CRD, gives the
  node two fake GPUs, starts both controllers, and runs `tests/e2e`. Those tests delete a running
  Deployment and a Certificate and check that both come back, check that the Secret is issued, check
  that the second team job waits for the first, and check that deleting a running job removes its
  batch Job.

## Limits

- The controllers run as processes outside the cluster in the e2e test, using a kubeconfig. The
  manifests for running them inside the cluster (image and RBAC) are not written yet.
- There is no leader election, so run only one copy of each controller.
- The GPU capacity is a number in the quota file, not read from the nodes. Keep it in line with the
  real GPU count.
