# Design notes

I keep the Python runtime dependencies in the standard library. Each role runs as its own process and Kubernetes Deployment. Sharing one image avoids maintaining four nearly identical base images; it does not give each role the other roles' credentials.

## Data flow and crash handling

1. Intake authenticates a client and accepts only named devices and scripts.
2. Audit authenticates intake, validates the request again and inserts the job plus its first event in a SQLite transaction. A unique request key prevents duplicate submissions.
3. A worker authenticates with a separate token and claims the oldest queued job. `BEGIN IMMEDIATE` serializes competing claims. Only one worker gets that lease.
4. The worker reads simulated version data and, for a link check, interface states. A down interface is a failed check, not a transport error.
5. Audit accepts a completion only for the current, unexpired lease and writes the terminal state and event together. Public responses never include lease tokens.
6. A later claim requeues expired jobs. Three expired attempts produce a terminal failure. A result lost in transit can lead to another read-only check, so this is at-least-once execution, not exactly-once device activity.

The queue caps outstanding jobs at 1,000. Completed history remains until the local cluster is removed. The volume is 1 GiB and has no automatic retention policy; a long-running installation needs retention, backups, storage monitoring and restore tests. The audit Deployment uses `Recreate` with one replica, because SQLite and this local volume are not a shared multi-writer database. PostgreSQL would be the next step for availability or larger workloads.

## Permissions

| Role | Secret values it receives | Permitted outbound application traffic |
| --- | --- | --- |
| Client | client token | intake:8080 |
| Intake | client token, intake token | audit:8080 |
| Worker | worker token, device token | audit:8080, device:8080 |
| Audit | intake token, worker token | none |
| Simulated device | device token | none |

All pods can query only the cluster DNS service on TCP/UDP 53. Pod selectors select peers in the same namespace. The namespace enforces Kubernetes' restricted pod security profile. Application pods have CPU/memory requests and limits, seccomp's default syscall filter, no privilege escalation, dropped capabilities and no mounted service-account tokens. No RBAC grants are needed because the applications never call the Kubernetes API.

The application write surface is the audit volume. Python bytecode writes are disabled, and no temporary writable root mount is required. HTTP request bodies and tokens are never logged. Liveness measures the process; readiness checks the database, audit dependency or worker polling heartbeat. A worker becomes unready if it has not contacted audit for 30 seconds.

## Boundaries and limitations

This demonstrates container restrictions, service authentication and enforced network isolation in a trusted local cluster. NetworkPolicy is not identity authentication: someone allowed to create pods and choose labels can impersonate a network role. Tokens provide a second boundary, but cluster administrators can read them. Kubernetes Secrets are base64 encoded by the API and are not automatically encrypted at rest here. Internal HTTP does not encrypt tokens on the wire. A production system needs TLS, tighter operator RBAC, external secret management and staged credential rotation.

The simulated switch is a separate fixture, not a connection to real equipment. Its endpoints model read-only `show version` and `show interfaces` operations. There is no shell invocation, user-supplied URL, real network scan or arbitrary command endpoint. Real switch adapters need protocol authentication, validated parsing, timeouts and their own integration tests.

The standard-library HTTP server keeps deployment small but is suitable for this bounded local workload. It is not internet-facing infrastructure, has no per-client rate limiting and is not a replacement for a production HTTP gateway. Probe routes reveal only health. The external API shares one client token rather than implementing per-user access control.

## Reproducibility and scanning

The kind tool, node image digest, Calico release and Trivy version are fixed in the workflow/scripts. The image removes pip and its bundled installer because I do not install packages at runtime. This also removes unused packaging dependencies caught by the image scan. The Python base tag deliberately receives fresh patch updates, and `apt-get upgrade` applies current OS fixes; exact base bytes can change between builds. CI scans the actual built image, and the Trivy JSON records its image ID and findings. A high or critical vulnerability with an available fix blocks CI. Unfixed vulnerabilities remain visible in the full report rather than being described as absent.

References: [Kubernetes security contexts](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/), [NetworkPolicies](https://kubernetes.io/docs/concepts/services-networking/network-policies/), and [Calico on kind](https://docs.tigera.io/calico/latest/getting-started/kubernetes/kind).
