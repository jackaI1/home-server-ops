# ServiceApp operator

The operator runs the home server's services from one small object per service.
Instead of restarting each service by hand, I write what I want to run in a
`ServiceApp`, and the operator makes the Deployment and Service match it. It also
checks the service's health path and writes the result into the object's status.

The code is in `k8s/operator`. It is written in Go with controller-runtime, the
library most Kubernetes controllers use. The chart is in `k8s/operator/chart`.

## The object

```yaml
apiVersion: homeops.local/v1alpha1
kind: ServiceApp
metadata:
  name: web
  namespace: default
spec:
  image: nginx        # container image without a tag
  version: 1.27-alpine
  port: 80            # port the container listens on (default 80)
  healthPath: /       # path the operator checks (default /)
  replicas: 1         # pods to keep running (default 1)
```

To update a service, change `version` and apply the file. The operator updates
the Deployment, Kubernetes rolls the pods over, and the status reports when the
rollout has finished.

## The status

`kubectl get serviceapps` shows the two conditions:

| Condition | True when | False when |
| --- | --- | --- |
| `Ready` | the Deployment is running the requested version on all replicas | the rollout is still going, the deadline was missed, or the Deployment has not caught up |
| `HealthCheck` | `GET` on the health path through the Service returns a 2xx status | the request fails, times out or returns a non-2xx status (the reason and message say which) |

`status.deployedVersion` shows the version the operator last applied.

## Install

The chart installs the CRD, a ServiceAccount, the RBAC rules and the operator.
Build the image on the server or your laptop, then load it into k3s the same way
the telemetry image is loaded (see [Kubernetes notes](kubernetes.md)):

```sh
docker build -t serviceapp-operator:0.1.0 k8s/operator
docker save serviceapp-operator:0.1.0 | sudo k3s ctr images import -
helm install serviceapp-operator k8s/operator/chart \
  --namespace homeops-system --create-namespace \
  --set image.pullPolicy=IfNotPresent
kubectl apply -f k8s/operator/config/samples/homeops_v1alpha1_serviceapp.yaml
kubectl get serviceapps
```

Helm installs CRDs only on the first install. When the CRD changes, apply the
new file from `chart/crds/` by hand with `kubectl apply --server-side`.

## Checks

| Command | What it does |
| --- | --- |
| `make test` | unit tests for the builders and the status logic |
| `make test-envtest` | reconciler tests against a real kube-apiserver and etcd (downloads about 165 MB once) |
| `make lint` | golangci-lint |
| `make helm-lint` | Helm lint in strict mode |
| `make smoke` | apply a ServiceApp, bump the version, break the health path and restore it, then delete it |

CI runs all of these on every pull request. The smoke test runs on a kind
cluster with the chart installed.

## Limitations

- The operator has no rollback. If a new version fails, change `version` back.
- Health checks run from the operator's pod through the Service. They do not
  check every pod, only what the Service routes to.
- It manages one container per ServiceApp, and it does not handle secrets. Put
  secrets in a Secret and mount it by hand until that is needed.
