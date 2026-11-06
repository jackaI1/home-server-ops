# Home server operations

I built a set of small tools for looking after a home server because I wanted a practical way to learn how to keep a system organized and respond to problems. They use sample data so I can try them without exposing my own machines or records.

The inventory checks installed software against a saved public vulnerability record and highlights machines with missing ownership tags. The ticket desk sorts requests, assigns them to a queue and reports how long they wait. The alert tools test detection rules against sample logs and gather evidence for a person to review. A small telemetry service records simulated satellite passes, and a Windows module covers routine administration.

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

## How it works

The inventory uses CPEs, standardized names for software, from a CSV scan. It compares them with a checksum-verified NVD snapshot and CISA's known-exploited list. Risk is CVSS severity plus five for known exploitation and one to three for asset criticality. Change `inventory/status.json` to record a finding's status and date. The included NVD snapshot covers one CVE, not the full database; complex configurations and version formats it cannot compare are skipped. A clean report is not proof a machine is safe.

The ticket desk stores requests in SQLite, a local database. Its rules file defines category, priority, queues and response targets. It checks for missing details and exact duplicates before assigning the least-loaded queue. The report measures elapsed time from creation to closure, or to the report time for open tickets. The simple local web page lists the queue and flags aging, stalled and unassigned requests.

Detection rules use a small supported subset of Sigma, a common format for describing log patterns. The converter makes parameterized SQLite queries, checks labeled examples and writes an ATT&CK coverage table. The alert workflow takes an interchangeable intelligence client; the included client returns unknown, so uncertain alerts go to a person. The optional summary callback cannot change routing.

The telemetry API stores simulated pass records in PostgreSQL. Kubernetes runs the service and database as containers, and Terraform describes the resources. The example database is temporary and its password is for local use only. The PowerShell module provides cautious Windows operations with `-WhatIf` and a JSON audit trail. See [operator notes](docs/operations.md) for setup, limitations and examples.

## Checks

GitHub Actions runs Python tests and detection checks, builds the telemetry image, and runs Pester tests on Windows Server. The sample detection report shows precision and recall on synthetic examples, not performance against real traffic.

## Other things I've built here

- [Entra access review](projects/entra-access-review/)
- [IP routing daemon](projects/ip-routing-daemon/)
- [IP routing troubleshooting lab](projects/ip-routing-troubleshooting-lab/)
- [Kubernetes automation services](projects/k8s-automation-services/)
- [Phishing header analyzer](projects/phish-header-analyzer/)
- [Vulnerability remediation tracker](projects/vuln-remediation-tracker/)
