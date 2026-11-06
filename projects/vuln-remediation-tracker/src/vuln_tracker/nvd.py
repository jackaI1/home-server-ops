"""Checksum-pinned public NVD API 2.0 severity enrichment."""

import hashlib
import json
import math
from pathlib import Path


def severity(score):
    if score is None:
        return "unknown"
    if score >= 9:
        return "critical"
    if score >= 7:
        return "high"
    if score >= 4:
        return "medium"
    if score > 0:
        return "low"
    return "none"


class Snapshot:
    def __init__(self, records, checksum):
        self.records, self.checksum = records, checksum

    def lookup(self, cve):
        return self.records.get(cve, {"score": None, "severity": "unknown", "vector": None})


def load_snapshot(path: Path, manifest: Path) -> Snapshot:
    raw = Path(path).read_bytes()
    expected = json.loads(Path(manifest).read_text())["sha256"]
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError("NVD snapshot checksum mismatch")
    records = {}
    for item in json.loads(raw)["vulnerabilities"]:
        cve = item["cve"]
        metrics = cve.get("metrics", {})
        score, vector = None, None
        for version in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            choices = metrics.get(version, [])
            if choices:
                metric = sorted(
                    choices,
                    key=lambda m: (m.get("source") != "nvd@nist.gov", m.get("type") != "Primary"),
                )[0]
                data = metric["cvssData"]
                score, vector = float(data["baseScore"]), data.get("vectorString")
                if not math.isfinite(score) or not 0 <= score <= 10:
                    raise ValueError("Invalid NVD score")
                break
        records[cve["id"]] = {"score": score, "severity": severity(score), "vector": vector}
    return Snapshot(records, actual)
