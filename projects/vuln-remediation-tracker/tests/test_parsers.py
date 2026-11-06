import hashlib
import json
from pathlib import Path

import pytest

from vuln_tracker.nvd import load_snapshot
from vuln_tracker.parsers import parse_scan

FIXTURES = Path(__file__).parent / "fixtures"


def test_nmap_deduplicates_and_ignores_negative_results():
    scan = parse_scan(FIXTURES / "nmap-before.xml")
    assert scan.source == "nmap"
    assert scan.assets == {"192.0.2.10", "192.0.2.20"}
    assert {(f.asset, f.cve) for f in scan.findings} == {
        ("192.0.2.10", "CVE-2021-41773"),
        ("192.0.2.20", "CVE-2021-44228"),
    }
    assert len(scan.findings) == 2


def test_greenbone_modern_refs_legacy_cve_and_empty_host():
    scan = parse_scan(FIXTURES / "greenbone.xml")
    assert scan.source == "greenbone"
    assert scan.assets == {"192.0.2.10", "192.0.2.30"}
    assert {f.cve for f in scan.findings} == {"CVE-2021-41773", "CVE-2014-0160"}


@pytest.mark.parametrize(
    "xml",
    [
        "<not-a-scan/>",
        "<nmaprun>",
        '<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><nmaprun>&xxe;</nmaprun>',
        '<nmaprun><runstats><finished exit="error"/></runstats></nmaprun>',
        "<report><scan_run_status>Running</scan_run_status><results/></report>",
    ],
)
def test_rejects_invalid_failed_or_unsafe_xml(tmp_path, xml):
    path = tmp_path / "bad.xml"
    path.write_text(xml)
    with pytest.raises(ValueError):
        parse_scan(path)


def test_snapshot_is_pinned_and_unknown_is_explicit(tmp_path):
    snapshot = load_snapshot(Path("data/nvd-snapshot.json"), Path("data/nvd-manifest.json"))
    assert snapshot.lookup("CVE-2021-41773")["score"] == 9.8
    assert snapshot.lookup("CVE-1900-9999")["severity"] == "unknown"
    path = tmp_path / "tampered.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        load_snapshot(path, Path("data/nvd-manifest.json"))


def test_snapshot_prefers_nvd_primary_score(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(
        json.dumps(
            {
                "vulnerabilities": [
                    {
                        "cve": {
                            "id": "CVE-2021-41773",
                            "metrics": {
                                "cvssMetricV31": [
                                    {
                                        "source": "vendor",
                                        "type": "Secondary",
                                        "cvssData": {"baseScore": 5.0},
                                    },
                                    {
                                        "source": "nvd@nist.gov",
                                        "type": "Primary",
                                        "cvssData": {"baseScore": 7.5},
                                    },
                                ]
                            },
                        }
                    }
                ]
            }
        )
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}))
    assert load_snapshot(path, manifest).lookup("CVE-2021-41773")["score"] == 7.5
