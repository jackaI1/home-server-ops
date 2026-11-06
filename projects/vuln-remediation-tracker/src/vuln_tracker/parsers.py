"""Read explicit CVE evidence, never guess vulnerabilities from a service name."""

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

CVE = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.I)
MAX_XML = 20 * 1024 * 1024


def asset_id(value: str) -> str:
    try:
        return str(ip_address(value.strip()))
    except ValueError as exc:
        raise ValueError(f"Invalid asset IP: {value!r}") from exc


@dataclass(frozen=True)
class Finding:
    asset: str
    cve: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class Scan:
    source: str
    assets: set[str]
    findings: tuple[Finding, ...]
    checksum: str
    complete: bool
    unmapped: int


def parse_scan(path: Path) -> Scan:
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_XML + 1)
    if len(raw) > MAX_XML:
        raise ValueError("XML exceeds the 20 MiB input limit")
    try:
        root = fromstring(raw)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise ValueError(f"Invalid or unsafe XML: {exc}") from exc
    # Greenbone exports sometimes include a default namespace.
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    assets, evidence = set(), {}
    unmapped = 0

    def add(asset, text, detail):
        nonlocal unmapped
        cves = set(x.upper() for x in CVE.findall(text))
        if not cves:
            unmapped += 1
        for cve in cves:
            evidence.setdefault((asset, cve), set()).add(detail[:2000])

    if root.tag == "nmaprun":
        source = "nmap"
        finished = root.find("./runstats/finished")
        if finished is not None and finished.get("exit") == "error":
            raise ValueError("Nmap scan failed")
        complete = finished is not None and finished.get("exit") == "success"
        for host in root.findall("./host"):
            if host.get("timedout", "false").lower() == "true":
                complete = False
            if host.find("./status") is None or host.find("./status").get("state") != "up":
                continue
            address = next(
                (a for a in host.findall("./address") if a.get("addrtype") in ("ipv4", "ipv6")),
                None,
            )
            if address is None:
                raise ValueError("Live Nmap host has no IP address")
            asset = asset_id(address.get("addr", ""))
            assets.add(asset)
            scripts = [(s, "host") for s in host.findall("./hostscript/script")]
            for port in host.findall("./ports/port"):
                if port.find("./state") is not None and port.find("./state").get("state") == "open":
                    scripts.extend(
                        (s, f"{port.get('portid')}/{port.get('protocol')}")
                        for s in port.findall("./script")
                    )
            for script, location in scripts:
                output = script.get("output", "")
                if re.search(r"(ERROR|timed out|failed to execute)", output, re.I):
                    complete = False
                # NSE vulns tables carry a state per vulnerability. Keep positive
                # siblings even when another CVE is explicitly NOT VULNERABLE.
                state_tables = [
                    t for t in script.iter("table") if t.find("./elem[@key='state']") is not None
                ]
                if state_tables:
                    for table in state_tables:
                        state = table.findtext("./elem[@key='state']", "").upper()
                        if not state.startswith(
                            ("VULNERABLE", "LIKELY VULNERABLE", "NOT VULNERABLE")
                        ):
                            complete = False
                        if "VULNERABLE" in state and "NOT" not in state:
                            text = ET.tostring(table, encoding="unicode")
                            add(asset, text, f"{location} {script.get('id')}: {text}")
                elif "NOT VULNERABLE" not in output.upper():
                    text = ET.tostring(script, encoding="unicode")
                    add(asset, text, f"{location} {script.get('id')}: {text}")
    elif root.tag in ("report", "get_reports_response"):
        source = "greenbone"
        if root.tag == "get_reports_response" and root.get("status", "200") != "200":
            raise ValueError("Greenbone report request failed")
        statuses = [n.text for n in root.iter("scan_run_status")]
        if statuses and any(s != "Done" for s in statuses):
            raise ValueError("Greenbone scan is not Done")
        complete = bool(statuses) and next(root.iter("error"), None) is None
        for node in root.findall(".//host/ip"):
            assets.add(asset_id(node.text or ""))
        for result in root.iter("result"):
            asset = asset_id(result.findtext("./host", ""))
            assets.add(asset)
            threat = result.findtext("threat", "").strip().lower()
            if threat == "false positive":
                continue
            if threat == "error" or result.findtext("severity", "") in ("-1", "-1.0"):
                complete = False
                continue
            nvt = result.find("./nvt")
            text = ET.tostring(nvt, encoding="unicode") if nvt is not None else ""
            add(
                asset,
                text,
                f"{result.findtext('port', 'host')} "
                f"{result.findtext('name', '')}: {result.findtext('description', '')}",
            )
        # Filtered/paginated reports cannot validate absence safely.
        for count in root.iter("result_count"):
            values = [count.findtext(key) for key in ("full", "filtered", "page")]
            counts = [int(v) for v in values if v is not None]
            if len(set(counts)) > 1:
                complete = False
    else:
        raise ValueError("Unsupported XML root; expected Nmap or Greenbone report")
    findings = tuple(
        Finding(a, c, tuple(sorted(details))) for (a, c), details in sorted(evidence.items())
    )
    return Scan(source, assets, findings, hashlib.sha256(raw).hexdigest(), complete, unmapped)
