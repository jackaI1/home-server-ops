# Home server operations

I built a set of small tools for looking after a home server because I wanted a practical way to learn how to keep a system organized and respond to problems. They use sample data so I can try them without exposing my own machines or records.

The inventory checks installed software against a saved public vulnerability record and highlights machines with missing ownership tags. The ticket desk sorts requests, assigns them to a queue and reports how long they wait. The alert tools test detection rules against sample logs and gather evidence for a person to review. A small telemetry service records simulated satellite passes, and a Windows module covers routine administration. The Linux part sets up the server from a clean install and shows why a backup is slow. I also added a small controller that keeps each service on the version I set, so an update is a one-line change.
I also added a monitoring stack that tells me when the LifeOS demo, a disk or a backup fails, and a model server that restarts and updates without me watching each step.

## Try it

Install Python 3.11, then from the project folder:

```sh
python -m pip install -r requirements.txt
python -m inventory.main
cat inventory/report.md
python -m helpdesk.main --db tickets.db add --subject 'Printer broken' --description 'Cannot print' --requester 'Example'
python -m helpdesk.main --db tickets.db report
python -m helpdesk.main --db tickets.db serve
```

The ticket view is at http://127.0.0.1:8000. Stop it with Ctrl-C. The report command writes `sla.csv` and `sla.xlsx`. To try the other examples:

```sh
python -m detection.main
python -m soar.main
python -m pytest -q tests
```

The Kubernetes chart tests need `helm` installed, and you run them with `python -m pytest -q k8s/tests`. The packet analysis tests need `tshark` and run with `python -m pytest -q netdiag/tests`.

## How it works

The sample report lists one open finding for the tagged desk node and places the other sample asset in the missing-tags queue. A finding is a software issue that needs investigation; a CVE number is its public identifier. The NVD is a public catalog of those issues, while CISA maintains a list of issues known to be exploited.

The inventory uses CPEs, standardized names for software, from a CSV scan. It compares them with a checksum-verified NVD snapshot and CISA's known-exploited list. Risk is CVSS severity plus five for known exploitation and one to three for asset criticality. Change `inventory/status.json` to record a finding's status and date. The included NVD snapshot covers one CVE, not the full database; complex configurations and version formats it cannot compare are skipped. A clean report is not proof a machine is safe.

The ticket desk stores requests in SQLite, a local database. Its rules file defines category, priority, queues and response targets. It checks for missing details and exact duplicates before assigning the least-loaded queue. The report measures elapsed time from creation to closure, or to the report time for open tickets. The simple local web page lists the queue and flags aging, stalled and unassigned requests.

Detection rules use a small supported subset of Sigma, a common format for describing log patterns. The converter makes parameterized SQLite queries, checks labeled examples and writes an ATT&CK coverage table. The alert workflow takes an interchangeable intelligence client; the included client returns unknown, so uncertain alerts go to a person. The optional summary callback cannot change routing.

The telemetry API stores simulated pass records in PostgreSQL. Both run on k3s, a small Kubernetes cluster on the home server. Helm packages them with resource limits, health checks and network policies that block all traffic unless it is allowed. Terraform installs them and keeps the database password out of Git. Each night a backup job dumps the database. The details are in [Kubernetes notes](docs/kubernetes.md). The PowerShell module provides cautious Windows operations with `-WhatIf` and a JSON audit trail. See [operator notes](docs/operations.md) for setup, limitations and examples.

## Kubernetes on k3s

I built a way to run the telemetry service on my home server so its records survive a restart, because the first version kept them in a temporary place and a restart could wipe them. The telemetry service is the small program that stores simulated satellite passes. The new setup runs it in Kubernetes, a program that starts, watches and restarts the apps on a server. The records now sit on a disk that survives restarts, and a backup copy is saved every night and can be restored.

The chart in `k8s/charts/home-ops` runs the API, PostgreSQL, the backup job and the network policies. Each pod has CPU and memory limits, and the API has health checks. The namespace refuses pods that run as root. The API is not exposed to the network: a default-deny policy blocks all traffic, and only the API may reach the database. Terraform in `k8s/terraform` creates the namespace and the database password Secret from an environment variable, then installs the chart.

To deploy it, follow the steps in [Kubernetes notes](docs/kubernetes.md). The short version:

```sh
export TF_VAR_postgres_password="$(openssl rand -hex 16)"
terraform -chdir=k8s/terraform init
terraform -chdir=k8s/terraform apply -var kube_context=default
kubectl -n home-ops port-forward service/telemetry 8000:80
```

The backups are dumps written to a volume on the same machine. Copy them off the server, and see the notes for how to restore one.

## Linux setup and slow transfers

I built a setup playbook and a packet analysis tool because my backups and syncs were slow, and I could not tell whether the network, the DNS lookups or one connection was to blame. A packet is one small piece of data sent over the network, and a capture is a saved record of every packet during one job.

The playbook in `ansible/` builds the home server from a clean Ubuntu install. Ansible runs its steps over SSH, so I can run it again after a reinstall and get the same result. It installs the packages I use, turns on automatic security updates, turns off password logins, and installs the packet tools. The steps and the test that checks them are in [Linux setup notes](docs/linux-setup.md).

The `netdiag` tool records the packets while a backup runs, then reads the saved file and writes a report:

```sh
sudo python3 -m netdiag run --iface eth0 --out ~/captures/backup-today -- /usr/local/bin/backup.sh
```

The report answers three questions. Were many packets sent a second time? That usually means packets were lost on the way. Did any DNS lookup take longer than 200 ms? Did any connection move less than 1 Mbit/s? Each finding names the connection or the lookup, so I know where to look. The steps for reading a report are in the [slow transfer runbook](docs/slow-transfer-runbook.md).

A report that never shows a problem proves nothing, so the repository has a fault drill. On a Linux machine it adds 5% packet loss to the loopback interface with `tc netem`, a tool that can make a network lossy on purpose, and checks that the report catches it. A clean run with no loss has to pass too.

The technical parts: `netdiag/capture.py` starts tcpdump and stops it in a `finally` block, so it cannot be left running. `netdiag/analyze.py` runs `tshark` with display filters for TCP, retransmissions and DNS, then works out per-connection throughput and the retransmission share. `netdiag/report.py` writes the Markdown. The unit tests use two sample captures in `netdiag/samples/`, generated by `make_samples.py` with fixed values, so they run the same way every time. The drill script is `netdiag/drill/netem_drill.sh`. GitHub Actions runs the tests, the drill and the playbook checks in `.github/workflows/linux-admin.yml`.

## A small Kubernetes operator

I built a Go controller for my services because updating one meant editing its Deployment by hand, watching the rollout, and checking by hand whether the service still answered. The controller reads a `ServiceApp` object that says which image and version to run and which path to check. It then makes the Deployment and Service match, and writes the result into the object.

A Kubernetes operator is a program that watches its own kind of object and keeps the cluster matching it. Here, the object is `ServiceApp`, defined by a CustomResourceDefinition (CRD). To update a service, I change the `version` line and apply the file. The status then shows two conditions: `Ready` (the new version has rolled out) and `HealthCheck` (the health path answers, or it says why not). The operator and its settings are packaged as a Helm chart in `k8s/operator/chart`. Usage, the status table and the limits are in [operator notes](docs/serviceapp-operator.md).

The code is in `k8s/operator`. It uses controller-runtime, the library most Go controllers are built on. The reconciler tests run against a real Kubernetes API server and etcd through envtest, and the smoke test installs the chart on a kind cluster, bumps the version and breaks a health path to check that the status catches it. CI builds the code, lints it and runs both test levels.

## Monitoring and alerts

I built a monitoring stack for my home server because I want to hear about a failure when it happens, not when I next check. The things I care about most are the LifeOS demo, which I run myself, and the nightly backups. Monitoring means a set of small programs collect numbers about the server every 30 seconds and check them against rules I wrote. When a rule is broken for long enough, I get a message.

It watches three things: whether the LifeOS demo answers in a browser, whether a disk is running out of room, and whether last night's backup finished and passed its check. Each alert waits a few minutes before it fires, so one slow page does not wake me. Every alert has a short page in `monitoring/runbooks/` that says what it means and what to do first.

To start it on the server:

```sh
cd monitoring
cp .env.example .env          # then set GRAFANA_ADMIN_PASSWORD in .env
docker compose up -d --wait
```

The dashboard is at http://127.0.0.1:3000 on the server. The ports only listen on localhost, so from my laptop I reach it through an SSH tunnel and nothing is exposed to my network. The setup steps, the list of alerts and the limits are in [monitoring notes](docs/monitoring.md).

The technical parts: Docker Compose starts Prometheus (which collects and checks the numbers), node_exporter (host CPU, memory and disks), blackbox_exporter (which requests the LifeOS demo and reads its certificate expiry), Alertmanager (which groups alerts and sends them on) and Grafana (dashboards, set up from files in Git). The backup job writes a timestamp only after `gzip -t` passes, and Prometheus reads that timestamp to tell whether the last good backup is more than 26 hours old. A disk alert fires only when the trend says it will fill within a day and less than a quarter is free, so a log that grows at night does not page me. The alert rules are tested with `promtool`: each rule has cases that show it firing when it should and staying quiet for short blips. The playbooks in `ansible/` deploy the stack and run the restart and restore steps. CI boots the whole stack and checks that every target is up.

Two limits. The alerts currently go to a small stand-in receiver that prints them, until I choose email or a phone notification. And the LifeOS health path (`/healthz`) is an assumption I still need to confirm against the app.

## A model server that restarts and updates safely

I built a Kubernetes setup for my local model server because I wanted it to restart and update without me watching each step, and to go back to the last working version if an update broke. Kubernetes is a program that runs containers and keeps them running. The server only receives requests once it reports that its model has loaded (the readiness check). A stuck process is restarted (the liveness check). Each copy has a memory and CPU limit, and an autoscaler adds a copy when the load is high. An update replaces one copy at a time, so there is always a working one to answer.

The server in `k8s/model-serving/app` is a stand-in that returns a fixed reply. I did not want to download model weights onto this Mac, so the deployment is what is real: it has the same endpoints a real model server would, and the chart and the checks do not change when I swap in a real image.

To deploy it and test a rollout on a local kind cluster (kind runs a small Kubernetes cluster inside Docker):

```sh
helm upgrade --install model-server k8s/model-serving/chart -n model-serving --create-namespace --set image.tag=0.2.0 --wait
NS=model-serving EXPECT_VERSION=0.2.0 k8s/model-serving/scripts/smoke.sh
```

`rollout_check.sh` goes through the whole sequence: it installs one version, rolls to the next one while a client sends 300 requests, then tries a version whose image does not exist. That broken rollout must fail, the working pods must keep answering, and the script rolls back and checks again. The details are in [model serving notes](docs/model-serving.md).

The technical parts: the Helm chart in `k8s/model-serving/chart` renders a Deployment with a `RollingUpdate` strategy (`maxUnavailable: 0`), readiness and liveness probes, resource requests and limits, a non-root security context with a read-only file system, a Service, and a HorizontalPodAutoscaler that targets 70% CPU between one and three replicas. The chart tests render it with Helm and check each of those settings. The server tests check the probe endpoints, and that requests get a 503 until the model has loaded.

## Checks

GitHub Actions runs Python tests and detection checks, builds the telemetry image, and runs Pester tests on Windows Server. The Linux workflow runs the packet analysis tests on stored captures, the `tc netem` fault drill, the Ansible lint and the molecule run on a clean Ubuntu container. The operator workflow runs gofmt, golangci-lint, the unit and envtest tests, Helm lint, and the smoke test on kind. A Kubernetes workflow lints the Helm chart, checks the rendered manifests against the Kubernetes schema, runs the chart and network policy tests, and deploys to a throwaway kind cluster. There it checks the backup and restore, and that pods outside the allowed paths cannot reach the API or the database. The sample detection report shows precision and recall on synthetic examples, not performance against real traffic.

A monitoring workflow checks the Prometheus rules with promtool, runs the alert unit tests, boots the monitoring stack and confirms every scrape target is up, and lints the Ansible playbooks. A model server workflow lints the chart, runs its tests, and deploys it to kind to test the rolling update, the failed rollout and the rollback.

## Other things I've built here

- [Entra access review](projects/entra-access-review/)
- [IP routing daemon](projects/ip-routing-daemon/)
- [IP routing troubleshooting lab](projects/ip-routing-troubleshooting-lab/)
- [Kubernetes automation services](projects/k8s-automation-services/)
- [Phishing header analyzer](projects/phish-header-analyzer/)
- [Vulnerability remediation tracker](projects/vuln-remediation-tracker/)
