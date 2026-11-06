"""Match installed CPEs against pinned NVD data and rank remediation work."""
import argparse, csv, hashlib, json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def snapshots():
    for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        path = ROOT.parent / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f'Checksum mismatch: {name}')
    return json.loads((ROOT / 'nvd.json').read_text()), json.loads((ROOT / 'kev.json').read_text())

def matches(installed, criteria):
    # CPE 2.3: compare each component; '*' in the NVD criterion is a wildcard.
    a, b = installed.lower().split(':'), criteria.lower().split(':')
    return len(a) == len(b) == 13 and all(y == '*' or x == y for x, y in zip(a, b))

def entry_matches(installed, entry):
    from packaging.version import Version, InvalidVersion
    if not matches(installed, entry['criteria']): return False
    try:
        version = Version(installed.split(':')[5])
        for key, op in [('versionStartIncluding', lambda a,b: a >= b), ('versionStartExcluding', lambda a,b: a > b), ('versionEndIncluding', lambda a,b: a <= b), ('versionEndExcluding', lambda a,b: a < b)]:
            if key in entry and not op(version, Version(entry[key])): return False
    except InvalidVersion:
        return not any(k.startswith('version') for k in entry)
    return True

def rank(cvss, exploited, criticality):
    return round(float(cvss) + (5 if exploited else 0) + {'high': 3, 'medium': 2, 'low': 1}.get(criticality.lower(), 0), 1)

def findings(assets, scans, nvd, kev, status):
    known = {x['cveID'] for x in kev['vulnerabilities']}
    result, untagged = [], []
    for asset in assets:
        if any(not asset.get(k) for k in ('owner', 'environment', 'criticality')):
            untagged.append(asset['id'])
            continue
        for scan in scans:
            if scan['asset_id'] != asset['id']: continue
            for item in nvd['vulnerabilities']:
                cve = item['cve']; cid = cve['id']
                for config in cve.get('configurations', []):
                    if config.get('operator') == 'AND' and len(config.get('nodes', [])) > 1: continue
                    for node in config.get('nodes', []):
                        for entry in node.get('cpeMatch', []):
                            # Range comparisons are intentionally not approximated.
                            if entry.get('vulnerable') and entry_matches(scan['cpe'], entry):
                                metrics = cve.get('metrics', {})
                                metric = next((metrics[k][0] for k in ('cvssMetricV31', 'cvssMetricV30', 'cvssMetricV2') if metrics.get(k)), None)
                                if not metric: continue
                                score = metric['cvssData']['baseScore']; state = status.get(f"{asset['id']}:{cid}", {})
                                result.append(dict(asset=asset['id'], cve=cid, cvss=score, exploited=cid in known, risk=rank(score, cid in known, asset.get('criticality', '')), status=state.get('status', 'open'), date=state.get('date', '')))
    return sorted(result, key=lambda x: -x['risk']), untagged

def main():
    p = argparse.ArgumentParser(); p.add_argument('--assets', default='inventory/assets.json'); p.add_argument('--scan', default='inventory/scan.csv'); p.add_argument('--status', default='inventory/status.json'); p.add_argument('--report', default='inventory/report.md'); p.add_argument('--set-status', nargs=3, metavar=('ASSET_CVE', 'STATUS', 'DATE')); a = p.parse_args()
    nvd, kev = snapshots(); assets = json.loads(Path(a.assets).read_text()); status = json.loads(Path(a.status).read_text())
    if a.set_status:
        key, state, when = a.set_status
        if state not in ('open', 'closed'): p.error('status must be open or closed')
        date.fromisoformat(when)
        status[key] = {'status': state, 'date': when}
        Path(a.status).write_text(json.dumps(status, indent=2) + '\n')
    with open(a.scan, newline='') as f: scans = list(csv.DictReader(f))
    rows, untagged = findings(assets, scans, nvd, kev, status)
    lines = ['# Vulnerability report', '', f'Generated: {date.today().isoformat()}', '', '## Open findings', '', '| Asset | CVE | CVSS | Known exploited | Risk | Status date |', '|---|---|---:|---|---:|---|']
    lines += [f"| {x['asset']} | {x['cve']} | {x['cvss']} | {x['exploited']} | {x['risk']} | {x['date']} |" for x in rows if x['status'] == 'open']
    lines += ['', '## Missing tags', ''] + [f'- {x}' for x in untagged]
    Path(a.report).write_text('\n'.join(lines) + '\n')
if __name__ == '__main__': main()
