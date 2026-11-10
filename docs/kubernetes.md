# Kubernetes deployment notes

This runs the telemetry API and its PostgreSQL database on a small Kubernetes cluster (k3s on the home server). The pieces are:

- `k8s/charts/home-ops`: a Helm chart with the API, the database, the nightly backup job and the network policies.
- `k8s/terraform`: Terraform creates the namespace, the database Secret and the Helm release.
- `k8s/tests` and `k8s/scripts/e2e-kind.sh`: tests for the chart and the policies, and a check on a throwaway kind cluster.
- `.github/workflows/kubernetes.yml`: runs all of the above on each pull request.

## Install k3s on the home server

k3s is a small Kubernetes distribution. Use the official installer and pin a version from the 1.31 line (see the k3s release notes for the current patch number):

```sh
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.31.<patch>+k3s1 sh -
```

k3s includes Traefik as its ingress controller in the `kube-system` namespace and a `local-path` storage class. Its built-in policy controller enforces NetworkPolicy objects. The chart allows traffic from `kube-system` for that reason.

Copy `/etc/rancher/k3s/k3s.yaml` to your laptop as `~/.kube/config`, then change `server:` to the server's address. The context is named `default` unless you rename it.

## Deploy

1. Build the API image and make it available to k3s. k3s does not read the Docker image store, so import it directly:

   ```sh
   docker build -f telemetry/Dockerfile -t telemetry:local .
   docker save telemetry:local | sudo k3s ctr images import -
   ```

2. Set the database password through the environment, not a file. It must be letters and digits, at least 24 characters:

   ```sh
   export TF_VAR_postgres_password="$(openssl rand -hex 16)"
   ```

3. Apply the Terraform module. Copy `k8s/terraform/terraform.tfvars.example` to `terraform.tfvars` if you want to keep your settings there:

   ```sh
   terraform -chdir=k8s/terraform init
   terraform -chdir=k8s/terraform apply -var kube_context=default
   ```

4. Check the release and reach the API from your laptop without opening any port on the network:

   ```sh
   kubectl -n home-ops get pods,cronjobs
   kubectl -n home-ops port-forward service/telemetry 8000:80
   ```

Terraform state is stored locally in `k8s/terraform/terraform.tfstate`. It contains the password, so keep that file out of Git and out of backups you do not control.

## What the chart runs

| Object | Purpose |
| --- | --- |
| `telemetry` Deployment | The FastAPI service. Readiness and liveness probes call `/health`. Read-only root filesystem, non-root user. |
| `postgres` StatefulSet | PostgreSQL 16 with a 5Gi volume (`pgdata` subdirectory) for its data. |
| `backup` CronJob | Runs `pg_dump` every night at 02:17 UTC and writes a gzip file to the `backups` volume. |
| `default-deny` policy | Blocks all ingress and egress for every pod in the namespace. |
| `allow-dns` policy | Lets pods ask cluster DNS for names. |
| `telemetry-ingress` policy | Lets only Traefik (`kube-system`) and labelled client pods reach the API. |
| `telemetry-egress` policy | Lets the API reach PostgreSQL on port 5432 and nothing else. |
| `postgres-ingress` policy | Lets only the API and backup pods reach PostgreSQL. |
| `backup-egress` policy | Lets backup pods reach PostgreSQL and nothing else. |

Every container has CPU and memory requests and limits. The namespace uses the Kubernetes `restricted` Pod Security level, so a pod that runs as root or allows privilege escalation is refused.

The chart refuses to render without `postgres.existingSecret`, and it refuses an empty `telemetry.ingress` list, because an empty `from:` list would allow all traffic.

## Backups

The `backup` job writes `telemetry-<UTC time>.sql.gz` to the `backups` volume. Before a dump is renamed into place, it is tested with `gzip -t`, so a half-written file never gets a `.sql.gz` name. Dumps older than `backup.retentionDays` (14 by default) are deleted.

Run a backup now:

```sh
kubectl -n home-ops create job --from=cronjob/backup manual-backup-$(date +%s)
kubectl -n home-ops logs job/<job-name>
```

To see what is on the backup volume, look on the k3s host. The `local-path` provisioner stores each volume as a directory under `/var/lib/rancher/k3s/storage/`:

```sh
sudo ls /var/lib/rancher/k3s/storage/ | grep home-ops_backups
```

Copy the dumps off the server. They are not encrypted, so encrypt them before copying them to another machine, for example with `age`:

```sh
sudo rsync -a /var/lib/rancher/k3s/storage/pvc-*_home-ops_backups/ /path/to/offsite/
```

### Restore

Restore into the running database only after you have a fresh dump of the current state. This example restores a dump named `telemetry-20261110T021702Z.sql.gz`:

```sh
kubectl -n home-ops scale deployment/telemetry --replicas=0
kubectl -n home-ops cp telemetry-20261110T021702Z.sql.gz postgres-0:/tmp/restore.sql.gz
kubectl -n home-ops exec postgres-0 -- sh -c '
  psql -U telemetry -d postgres -c "DROP DATABASE telemetry" -c "CREATE DATABASE telemetry OWNER telemetry" &&
  gunzip -c /tmp/restore.sql.gz | psql -U telemetry -d telemetry -v ON_ERROR_STOP=1 -q &&
  rm /tmp/restore.sql.gz'
kubectl -n home-ops scale deployment/telemetry --replicas=1
```

The restore is tested in CI. The end-to-end script backs up the database, restores the dump into a scratch database, and compares row counts with the live database.

Limits of this setup:

- The dumps and the database share one disk on one machine. A dump protects against a bad write or a deleted table. It does not protect against losing the disk. Copy dumps off the server.
- There is no point-in-time recovery. The worst case is the loss of up to one day of records.
- Storage is `local-path`, which does not snapshot volumes. Use a volume snapshot class if the storage backend supports one.
- The setup assumes one k3s node. `local-path` volumes live on the node that created them, so a second node would need a different storage class.

## Tests

Run the chart and policy tests locally (they need `helm`):

```sh
python -m pip install pytest==8.3.4 PyYAML==6.0.2
python -m pytest -q k8s/tests
```

`test_network_policies.py` renders the policies and checks named pod-to-pod flows, such as "a pod outside the namespace cannot reach PostgreSQL". `e2e-kind.sh` runs the same flows on a real cluster with Calico. A kind cluster is never created on the home server; CI creates one for each pull request.

To run the end-to-end script yourself, you need a kind cluster with a policy-enforcing CNI, a deployed release, and `kubectl` pointing at it. The script cleans up its probe pods and port-forward when it exits.
