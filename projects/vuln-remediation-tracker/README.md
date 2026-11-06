# vuln-remediation-tracker

I built a tool to track security problems on my computers to learn how the underlying idea works. This is a learning project.

## Try the example

```sh
uv sync --frozen --extra test
uv run vuln-tracker --db demo.sqlite ingest tests/fixtures/nmap-before.xml --scope lab --on 2026-01-01
uv run vuln-tracker --db demo.sqlite report --as-of 2026-01-09 --inventory data/inventory.csv
```

This starts with two new findings. Both are overdue on January 9, and the inventory check says the storage server was missing from the scan. These dates make the example repeatable; for my own scans I use their actual dates.

```sh
uv run vuln-tracker --db demo.sqlite update 192.0.2.10 CVE-2021-41773 --status pending_validation --owner 'Lab owner' --note 'Updated the web server'
uv run vuln-tracker --db demo.sqlite ingest tests/fixtures/nmap-after.xml --scope lab --on 2026-01-10 --complete-asset 192.0.2.10
uv run vuln-tracker --db demo.sqlite report --as-of 2026-01-11
```

The second scan validates one fix and finds the other problem again. The final report has **one fixed finding and one active, overdue finding**. I can use `--format json` on a report to export the stored evidence and transition history.

## Scan my own lab

I accept Nmap XML with explicit CVE identifiers from vulnerability scripts, and OpenVAS/Greenbone XML reports. A CVE is the public identifier for a known vulnerability. An ordinary Nmap port scan lists services, so it does not automatically produce vulnerability findings.

```sh
uv run vuln-tracker --db my-lab.sqlite ingest path/to/greenbone-report.xml --scope full-lab --on 2026-02-01
uv run vuln-tracker --db my-lab.sqlite report --inventory path/to/inventory.csv
```

The inventory is a CSV file with `asset,name,owner` columns. Assets are IP addresses. Reports compare the inventory with the **latest imported scan**, including computers with no findings. `--strict-inventory` exits with code 3 when computers are missing or unexpected, which makes the check usable in a script.

For a real, repeatable local scan, I included a small loopback lab:

```sh
brew install nmap                 # Ubuntu: sudo apt-get install nmap
uv run python scripts/run_lab.py
```

This runs real Nmap against a Python server on `127.0.0.1`, imports its XML, changes a synthetic Apache version banner, and rescans. It produces one new finding and one validated fix, plus XML, a SQLite database and a JSON report under `.lab-output/`. The script closes its server and verifies the socket is released, even if the scan fails. The banner is simulated; this demonstrates the scan-to-remediation workflow and does not prove that real Apache software was vulnerable or patched.

## How I track fixes

A finding is one IP address and one CVE, even when several ports or scanners report it. I keep scanner observations separately so a clean Nmap result cannot erase an outstanding Greenbone result. A scope is a stable name for a scanner configuration, such as `full-lab`.

An import normally adds evidence. `--complete-asset IP` is my explicit declaration that I reran every relevant port and vulnerability check for that computer, using the same scanner and scope. I only use it with an unfiltered, complete report. The computer must be present and live, and the scan must have finished successfully. A missing computer, incomplete scan or different scope cannot establish a fix. I must never declare a plain port scan complete for vulnerability validation. The tracker cannot check whether my coverage declaration is truthful.

I can assign an owner, change the due date with `update --due-date YYYY-MM-DD`, and use `open`, `in_progress` or `pending_validation`. Only a qualifying rescan can set `fixed`. If the vulnerability returns, the tracker reopens it and starts a new deadline. Reimporting the same file does not create duplicate history.

## Severity and deadlines

I enrich findings from three public [NVD records](https://nvd.nist.gov/), a US government vulnerability database, saved in `data/nvd-snapshot.json`. A SHA-256 checksum in `data/nvd-manifest.json` pins the exact file and records the download URLs and retrieval date. Ingestion checks it before changing the database and makes no network calls.

This is a small historical snapshot, not a current or complete vulnerability feed. Other CVEs still get tracked. [The operating notes](docs/usage.md) explain adding records, scan coverage, and the database fields.

## Tests and limits

There are 4 test source files in this copy. No test pass count is claimed here: I have not re-run the project suite as part of this move. This is a source snapshot, and running it on a new machine may need environment-specific setup.


Project checks run from this directory through the path-filtered hub workflows: `vuln-remediation-tracker-ci.yml`.
