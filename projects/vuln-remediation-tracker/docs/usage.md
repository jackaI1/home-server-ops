# Operating notes

## Import boundaries

Only scan systems I own or have permission to assess. The included executable lab uses loopback only. Fixture addresses use the documentation-only `192.0.2.0/24` range, not real assets. Scan results for my own machines stay local; `.gitignore` excludes databases and lab output.

Nmap imports read live IPv4/IPv6 hosts, host scripts and scripts on open ports. They accept explicit CVEs in NSE vulnerability tables and `vulners` output. A structured `NOT VULNERABLE` entry is ignored. Results based on versions remain candidates; scanner evidence is not proof of exploitability. Scripts with errors or unknown test states, and timed-out hosts, prevent complete-coverage validation. XML without successful finish metadata may add findings but cannot validate fixes.

Greenbone imports read CVE references in `nvt/refs/ref` and legacy `nvt/cve`, result host addresses, and clean hosts listed with `host/ip`. Download the full native XML report with all results, not a paginated GMP page or a filtered view. A `Done` run status is required for closure. Scanner errors and differing full/filtered/page result counts block closure. Explicit false-positive results are excluded. Host coverage absent from the XML cannot be declared complete. The tracker is intentionally conservative about asset identity: an address change needs operator review rather than silently merging two computers by hostname.

Keep each scanner configuration under the same `--scope`. Changing the scope creates an independent stream of evidence. A complete rescan only closes observations for its scanner and scope. All streams for a finding must close before its overall status becomes fixed. If a check was omitted, import without `--complete-asset`.

Imports must be chronological across a database. `--on` is the actual date I collected the scan. Equal dates are allowed. Identical source/scope/file bytes are idempotent; a second import does not add coverage declarations, even if flags differ. To correct a mistaken import, restore a database backup and replay the actual scans. I do not edit imported evidence in place.

`report --as-of` changes the overdue cutoff, not the recorded lifecycle state. It is not a historical reconstruction of the database. `latest_events` identifies the latest scan's new/recurring/reopened/fixed transitions. Each finding's history retains all transitions and scan IDs. Inventory validation always names the latest scan ID, source and scope in the report, so a narrow scan's missing assets are visible rather than combined with stale observations.

## Update the NVD snapshot

The committed snapshot contains original API 2.0 CVE records for CVE-2021-41773, CVE-2021-44228 and CVE-2014-0160. Source URLs and the actual retrieval timestamp are in `data/nvd-manifest.json`. The checksum detects accidental changes, not authenticity against someone who can replace both files.

To extend it, retrieve CVEs from the [official NVD API](https://nvd.nist.gov/developers/vulnerabilities), keep the `vulnerabilities` list of objects containing `cve`, and record the source URLs and retrieval time. Follow NVD's API rate limits. After reviewing the public records, compute the checksum:

```sh
python3 -c 'import hashlib; from pathlib import Path; print(hashlib.sha256(Path("data/nvd-snapshot.json").read_bytes()).hexdigest())'
```

Update `sha256` in the manifest, rerun tests, and review the changes together. `--snapshot PATH --manifest PATH` can use a separate pinned snapshot without changing the bundled one. Existing findings get refreshed severity when they next appear in a scan; existing deadlines are preserved. Every scan stores which checksum was used. No scanner-supplied score replaces a missing NVD score.

## Database and exit codes

The schema has five tables: `scans` for provenance and coverage, `findings` for the asset/CVE workflow, `observations` for scanner/scope evidence, `events` for scan transitions, and `activity` for owner/status/deadline notes. Scan events and operator notes are separate so a requested fix cannot impersonate a validation scan. Back up the SQLite file while no import is running.

Exit code 0 means the command succeeded. Code 2 means invalid input or a database/file error. Code 3 means an inventory mismatch when `--strict-inventory` was requested. Use `--format json` for reports consumed by another program. Inventory names and owners are labels; the tracker does not send notifications or perform patching.

## Parser references

- [Nmap XML output](https://nmap.org/book/output-formats-xml-output.html)
- [Nmap vulnerability states](https://nmap.org/nsedoc/lib/vulns.html)
- [Nmap vulners script](https://nmap.org/nsedoc/scripts/vulners.html)
- [Greenbone Management Protocol](https://greenbone.github.io/gvmd/gmp.html)
