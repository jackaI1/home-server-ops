# Operations notes

## Inventory

`inventory/assets.json` holds asset ID, owner, environment and criticality (`low`, `medium`, `high`). `inventory/scan.csv` maps asset IDs to CPE 2.3 strings. `inventory/status.json` is a JSON object keyed by `asset-id:CVE-id`, for example `{"desk-node:CVE-2021-44228":{"status":"closed","date":"2026-11-06"}}`. Open findings are sorted by score. Keep a change history separately if a full audit trail is required.

The pinned snapshots come from NVD's CVE API (CVE-2021-44228) and CISA's KEV JSON feed. `inventory/SHA256SUMS` detects changes; it does not authenticate the original download. Refresh both files from their official HTTPS endpoints and update the checksums together after review. The matcher supports simple CPE component wildcards and comparable version bounds; multi-node AND configurations are skipped. It is not a complete NVD configuration evaluator.

## Tickets and alerts

Edit `helpdesk/rules.json` to adjust queues and targets. SLA measures total calendar hours, not business hours. Use SQLite to update a ticket's status and `updated` timestamp when closing it. The web view binds to localhost and has no authentication; it is for a local demo. Follow-up text is returned when required fields are missing. Duplicate detection uses the same requester and subject on an open ticket.

Implement `lookup(kind, value)` on an intelligence client to return `verdict`, `confidence` (0 to 1), and `source`; see `soar/main.py`. `sweep` checks saved log lines for exact IOC strings. The default client does not contact an external service. No automatic containment is performed.

## Telemetry deployment

The local manifest includes an ephemeral PostgreSQL deployment: it is not suitable for valuable data. With Docker, kind, kubectl and Terraform installed, build the image from the repository root, create a cluster, load the image and apply the module:

```sh
docker build -f telemetry/Dockerfile -t telemetry:local .
kind create cluster --name telemetry
kind load docker-image telemetry:local --name telemetry
terraform -chdir=telemetry/terraform init
terraform -chdir=telemetry/terraform apply
kubectl -n telemetry port-forward service/telemetry 8000:80
```

POST JSON such as `{"satellite":"demo","observed_at":"2025-01-01T00:00:00Z","elevation":45}` to `/passes`; GET `/passes?satellite=demo` filters results. `kind delete cluster --name telemetry` removes the cluster. The Ansible playbook installs initial Debian host dependencies; kind, kubectl and Terraform must currently be installed separately.

## Windows

Run PowerShell as administrator where needed. Import with `Import-Module ./windows/HomeOps.psm1`; use `Get-HomeHealth`, or preview changes with e.g. `Ensure-HomeFirewallRule -Name Demo -Port 8080 -WhatIf`. Changes append JSON lines to `homeops-audit.jsonl`. Existing firewall rules and tasks are left unchanged, so inspect them before relying on their settings. Rotation tasks execute a script supplied by the operator. The module can create missing local users and groups, but does not install updates.
