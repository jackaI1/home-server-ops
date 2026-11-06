from pathlib import Path

import pytest

from vuln_tracker.parsers import parse_scan
from vuln_tracker.tracker import read_inventory


def test_greenbone_filtered_report_cannot_validate_absence(tmp_path):
    scan = tmp_path / "filtered.xml"
    scan.write_text("""<report><scan_run_status>Done</scan_run_status>
        <result_count><full>10</full><filtered>0</filtered><page>0</page></result_count>
        <host><ip>192.0.2.10</ip></host><results/></report>""")
    assert parse_scan(scan).complete is False


def test_greenbone_false_positive_is_not_a_finding(tmp_path):
    scan = tmp_path / "false-positive.xml"
    scan.write_text("""<report><scan_run_status>Done</scan_run_status><results>
        <result><host>192.0.2.10</host><threat>False Positive</threat><severity>-1.0</severity>
        <nvt><cve>CVE-2021-41773</cve></nvt></result></results></report>""")
    assert parse_scan(scan).findings == ()


def test_mixed_positive_negative_nmap_tables_keep_only_positive(tmp_path):
    scan = tmp_path / "mixed.xml"
    scan.write_text("""<nmaprun><host><status state="up"/>
      <address addr="2001:db8::1" addrtype="ipv6"/><hostscript>
      <script id="test" output="NOT VULNERABLE CVE-2014-0160; VULNERABLE CVE-2021-41773">
      <table key="CVE-2014-0160"><elem key="state">NOT VULNERABLE</elem></table>
      <table key="CVE-2021-41773"><elem key="state">VULNERABLE</elem></table>
      </script></hostscript></host><runstats><finished exit="success"/></runstats></nmaprun>""")
    assert [(f.asset, f.cve) for f in parse_scan(scan).findings] == [
        ("2001:db8::1", "CVE-2021-41773")
    ]


@pytest.mark.parametrize(
    "content",
    [
        "asset,name,owner\n192.0.2.10,A,Lab\n192.0.2.10,B,Lab\n",
        "asset,name,owner\nnot-an-ip,A,Lab\n",
        "asset\n192.0.2.10\n",
    ],
)
def test_inventory_rejects_duplicates_bad_ips_and_missing_columns(tmp_path, content):
    inventory = tmp_path / "inventory.csv"
    inventory.write_text(content)
    with pytest.raises(ValueError):
        read_inventory(inventory)


def test_xml_size_is_bounded(tmp_path):
    path = tmp_path / "large.xml"
    with path.open("wb") as stream:
        stream.truncate(20 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="limit"):
        parse_scan(path)


@pytest.mark.parametrize("modification", ["timeout", "unknown", "greenbone-error"])
def test_uncertain_checks_never_validate_a_fix(tmp_path, modification):
    from vuln_tracker.nvd import load_snapshot
    from vuln_tracker.tracker import Tracker

    fixtures = Path(__file__).parent / "fixtures"
    scan = tmp_path / "uncertain.xml"
    if modification == "greenbone-error":
        scan.write_text("""<report><scan_run_status>Done</scan_run_status>
            <host><ip>192.0.2.10</ip></host><results/>
            <errors><error><host>192.0.2.10</host><description>Authentication failed</description>
            </error></errors></report>""")
    else:
        text = (fixtures / "nmap-after.xml").read_text()
        if modification == "timeout":
            text = text.replace("<host>", '<host timedout="true">', 1)
        else:
            text = text.replace(
                '<script id="http-vuln-test" output="NOT VULNERABLE"/>',
                '<script id="http-vuln-test"><table key="CVE-2021-41773">'
                '<elem key="state">UNKNOWN (unable to test)</elem></table></script>',
            )
        scan.write_text(text)
    assert parse_scan(scan).complete is False
    snapshot = load_snapshot(Path("data/nvd-snapshot.json"), Path("data/nvd-manifest.json"))
    with Tracker(tmp_path / "tracker.sqlite", snapshot) as tracker:
        tracker.ingest(fixtures / "nmap-before.xml", "2026-01-01", "lab")
        with pytest.raises(ValueError, match="complete"):
            tracker.ingest(scan, "2026-01-02", "lab", ["192.0.2.10"])
        assert tracker.report("2026-01-03")["summary"]["fixed"] == 0


def test_greenbone_scanner_error_is_incomplete_even_if_done(tmp_path):
    scan = tmp_path / "error-result.xml"
    scan.write_text("""<report><scan_run_status>Done</scan_run_status><results>
        <result><host>192.0.2.10</host><threat>Error</threat><severity>-1.0</severity>
        <nvt><cve>CVE-2021-41773</cve></nvt></result></results></report>""")
    parsed = parse_scan(scan)
    assert parsed.findings == ()
    assert parsed.complete is False
