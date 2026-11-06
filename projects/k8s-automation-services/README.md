# k8s-automation-services

I built a small device-check service to learn how the underlying idea works. This is a learning project.

## How I split the work

I use three Python microservices, meaning small programs with separate responsibilities:

## Run it

For the Python tests, I need Python 3.12 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/):

```sh
uv sync --frozen
uv run pytest -q
```

For the complete cluster test, I need a running Docker engine, [kind](https://kind.sigs.k8s.io/docs/user/quick-start/) (tested with v0.33.0), kubectl and Python:

```sh
./scripts/kind-smoke.sh
```

To keep the cluster for my own checks:

```sh
./scripts/kind-smoke.sh --keep
export KUBECONFIG=/tmp/device-automation-evidence/kubeconfig
kubectl -n device-automation port-forward service/intake 8080:8080
```

## Container and network boundaries

I generate four different tokens as Kubernetes Secrets at deployment time. Each container gets only the tokens it needs; no credentials go into an image or a committed configuration file. Secrets are not a vault: this local setup does not enable encryption at rest, and someone with cluster administration access can read them.

I start with NetworkPolicies, Kubernetes traffic rules, that deny inbound and outbound traffic. I then allow only client-to-intake, intake-to-audit, worker-to-audit, worker-to-device and cluster DNS lookups. I install [Calico](https://docs.tigera.io/calico/latest/getting-started/kubernetes/kind) because kind's default network plugin does not enforce these rules. The smoke test attempts forbidden connections to prove isolation is active. See [the design and limitations](docs/design.md).

## Tests and limits

There are 4 test source files in this copy. No test pass count is claimed here: I have not re-run the project suite as part of this move. This is a source snapshot, and running it on a new machine may need environment-specific setup.


Project checks run from this directory through the path-filtered hub workflows: (removed workflow).

The relocated workflow did not complete successfully within the migration batch. Local test sources remain available.
