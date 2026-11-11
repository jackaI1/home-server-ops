# Model serving notes

This page covers the model server chart in `k8s/model-serving/`. The plain-language version is in the README.

## What is in the chart

- `chart/templates/deployment.yaml`: one Deployment with a rolling update (`maxSurge: 1`, `maxUnavailable: 0`), a readiness probe on `/ready`, a liveness probe on `/health`, CPU and memory requests and limits, and a restricted security context (non-root, read-only root filesystem, no capabilities).
- `chart/templates/service.yaml`: a ClusterIP Service on port 80.
- `chart/templates/hpa.yaml`: a `HorizontalPodAutoscaler` (autoscaling/v2) that targets 70% CPU between 1 and 3 replicas, with a two-minute scale-down window so short quiet periods do not flap.
- `app/server.py`: the stand-in server. Its `/ready` returns 503 for `MODEL_LOAD_SECONDS` after start, which is how a real model behaves while its weights load.

## The stand-in model

No model weights are included. The server returns a fixed reply and reports its `VERSION` (set from the image tag), so a rollout can be seen in each response. To serve a real model, build an image from your model server, keep the same `/health`, `/ready` and `/v1/generate` contract, and set `image.repository` and `image.tag`. The chart and the scripts do not change.

## Deploy and roll out

```sh
helm upgrade --install model-server k8s/model-serving/chart -n model-serving --create-namespace \
  --set image.tag=0.2.0 --wait
NS=model-serving EXPECT_VERSION=0.2.0 k8s/model-serving/scripts/smoke.sh
```

`rollout_check.sh` runs the whole sequence on a cluster that has both image tags loaded:

1. Install `0.1.0` and smoke test it.
2. Roll to `0.2.0` while an in-cluster client sends 300 requests. It expects zero failures.
3. Roll to a tag that does not exist. The rollout must fail, and the `0.2.0` pods must keep answering.
4. Roll back to the last good revision and smoke test again.

`smoke.sh` port-forwards the Service, checks `/health` and `/ready`, sends a generate request, and checks that the reply names the expected version.

## Tests

| Check | Where |
|---|---|
| `helm lint --strict`, `kubeconform` on the rendered manifests | CI `chart` job |
| `pytest k8s/model-serving/tests` (server endpoints, probes, limits, rolling update, HPA, service) | CI `chart` job |
| `rollout_check.sh` and `smoke.sh` on a kind cluster, with metrics-server, and an HPA `ScalingActive` check | CI `rollout` job |

## Limits

- The stub model is not a model. The tests show the deployment behaves like a model server, not that a particular model answers well.
- The HPA scales on CPU. A model that is slow but not CPU-bound (for example, a GPU model) would need a custom metric.
- kind runs one node, so the rollout check shows the pod order and readiness gating but not node failure.
