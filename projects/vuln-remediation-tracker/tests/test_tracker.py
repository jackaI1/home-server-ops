import sqlite3
from pathlib import Path

import pytest

from vuln_tracker.nvd import load_snapshot
from vuln_tracker.tracker import Tracker

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tracker(tmp_path):
    snapshot = load_snapshot(Path("data/nvd-snapshot.json"), Path("data/nvd-manifest.json"))
    with Tracker(tmp_path / "tracker.sqlite", snapshot) as tracker:
        yield tracker


def changed(tmp_path, original="nmap-before.xml", marker="another scan"):
    path = tmp_path / f"{marker}.xml"
    path.write_text((FIXTURES / original).read_text() + f"<!-- {marker} -->")
    return path


def test_new_recurring_fixed_and_overdue(tracker, tmp_path):
    first = tracker.ingest(FIXTURES / "nmap-before.xml", "2026-01-01", "lab")
    assert first["new"] == 2
    recurring = tracker.ingest(changed(tmp_path), "2026-01-02", "lab")
    assert recurring["recurring"] == 2
    report = tracker.report("2026-01-09")
    assert report["summary"]["overdue"] == 2
    assert report["findings"][0]["due_date"] == "2026-01-08"
    after = tracker.ingest(FIXTURES / "nmap-after.xml", "2026-01-10", "lab", ["192.0.2.10"])
    assert after["fixed"] == 1
    report = tracker.report("2026-01-11")
    assert report["summary"]["fixed"] == 1
    assert report["summary"]["overdue"] == 1
    assert report["findings"][0]["validated_scan_id"] == after["scan_id"]


def test_fix_request_cannot_close_without_complete_rescan(tracker):
    tracker.ingest(FIXTURES / "nmap-before.xml", "2026-01-01", "lab")
    tracker.update(
        "192.0.2.10",
        "CVE-2021-41773",
        "pending_validation",
        owner="Lab owner",
        note="Updated Apache",
        due_date="2026-01-12",
    )
    tracker.ingest(FIXTURES / "nmap-after.xml", "2026-01-02", "lab")
    item = tracker.report("2026-01-03")["findings"][0]
    assert item["status"] == "pending_validation"
    assert item["owner"] == "Lab owner"
    assert item["due_date"] == "2026-01-12"
    assert item["activity"][0]["note"] == "Updated Apache"
    with pytest.raises(ValueError, match="status"):
        tracker.update("192.0.2.10", "CVE-2021-41773", "fixed", note="Trust me")


def test_cross_source_and_scope_cannot_close_other_evidence(tracker, tmp_path):
    tracker.ingest(FIXTURES / "nmap-before.xml", "2026-01-01", "lab")
    tracker.ingest(FIXTURES / "greenbone.xml", "2026-01-02", "lab")
    tracker.ingest(changed(tmp_path), "2026-01-03", "other")
    result = tracker.ingest(FIXTURES / "nmap-after.xml", "2026-01-04", "lab", ["192.0.2.10"])
    assert result["fixed"] == 0
    item = next(f for f in tracker.report("2026-01-05")["findings"] if f["cve"] == "CVE-2021-41773")
    assert item["status"] == "open"
    assert len([x for x in item["observations"] if x["active"]]) == 2


def test_reopen_after_validated_fix_resets_due_date(tracker, tmp_path):
    tracker.ingest(FIXTURES / "nmap-before.xml", "2026-01-01", "lab")
    tracker.ingest(FIXTURES / "nmap-after.xml", "2026-01-02", "lab", ["192.0.2.10"])
    result = tracker.ingest(changed(tmp_path), "2026-02-01", "lab")
    assert result["reopened"] == 1
    item = tracker.report("2026-02-02")["findings"][0]
    assert item["status"] == "open"
    assert item["due_date"] == "2026-02-08"
    assert item["validated_scan_id"] is None
    assert [e["kind"] for e in item["history"]] == ["new", "fixed", "reopened"]


def test_duplicate_import_is_idempotent(tracker):
    first = tracker.ingest(FIXTURES / "nmap-before.xml", "2026-01-01", "lab")
    again = tracker.ingest(FIXTURES / "nmap-before.xml", "2026-01-02", "lab")
    assert again["duplicate"] is True
    assert again["scan_id"] == first["scan_id"]
    assert tracker.report("2026-01-02")["summary"]["scans"] == 1


@pytest.mark.parametrize("complete_assets", [["192.0.2.99"], ["not-an-ip"]])
def test_bad_coverage_is_atomic(tracker, complete_assets):
    with pytest.raises(ValueError):
        tracker.ingest(FIXTURES / "nmap-before.xml", "2026-01-01", "lab", complete_assets)
    assert tracker.report("2026-01-02")["summary"]["scans"] == 0


def test_backdated_scan_and_invalid_date_are_rejected(tracker, tmp_path):
    tracker.ingest(FIXTURES / "nmap-before.xml", "2026-01-10", "lab")
    with pytest.raises(ValueError, match="chronological"):
        tracker.ingest(changed(tmp_path), "2026-01-01", "lab")
    with pytest.raises(ValueError):
        tracker.ingest(FIXTURES / "nmap-after.xml", "2026-02-30", "lab")
    assert tracker.report("2026-01-11")["summary"]["scans"] == 1


def test_inventory_uses_latest_scan_not_historical_union(tracker, tmp_path):
    tracker.ingest(FIXTURES / "nmap-before.xml", "2026-01-01", "lab")
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("asset,name,owner\n192.0.2.10,Web,Lab\n192.0.2.30,Storage,Lab\n")
    result = tracker.report("2026-01-02", inventory)["inventory"]
    assert result["missing"] == ["192.0.2.30"]
    assert result["unexpected"] == ["192.0.2.20"]
    assert result["matched"] == ["192.0.2.10"]


def test_incomplete_metadata_or_script_error_cannot_validate_fix(tracker, tmp_path):
    tracker.ingest(FIXTURES / "nmap-before.xml", "2026-01-01", "lab")
    path = tmp_path / "incomplete.xml"
    for xml in [
        (FIXTURES / "nmap-after.xml").read_text().replace('<finished exit="success"/>', ""),
        (FIXTURES / "nmap-after.xml").read_text().replace("NOT VULNERABLE", "ERROR: timeout"),
    ]:
        path.write_text(xml)
        with pytest.raises(ValueError, match="complete"):
            tracker.ingest(path, "2026-01-02", "lab", ["192.0.2.10"])
    assert tracker.report("2026-01-03")["summary"]["fixed"] == 0


def test_unknown_cve_is_tracked_without_scanner_severity(tracker, tmp_path):
    path = tmp_path / "unknown.xml"
    path.write_text(
        (FIXTURES / "nmap-before.xml").read_text().replace("CVE-2021-41773", "CVE-2099-12345")
    )
    tracker.ingest(path, "2026-01-01", "lab")
    item = tracker.report("2026-01-02")["findings"][0]
    assert item["severity"] == "unknown"
    assert item["score"] is None
    assert item["due_date"] == "2026-01-31"


def test_database_persists_and_connections_close(tmp_path):
    path = tmp_path / "db.sqlite"
    snapshot = load_snapshot(Path("data/nvd-snapshot.json"), Path("data/nvd-manifest.json"))
    with Tracker(path, snapshot) as tracker:
        tracker.ingest(FIXTURES / "nmap-before.xml", "2026-01-01", "lab")
    with pytest.raises(sqlite3.ProgrammingError):
        tracker.db.execute("select 1")
    with Tracker(path, snapshot) as reopened:
        assert len(reopened.report("2026-01-02")["findings"]) == 2


def test_status_change_preserves_owner_unless_explicitly_changed(tracker):
    tracker.ingest(FIXTURES / "nmap-before.xml", "2026-01-01", "lab")
    tracker.update(
        "192.0.2.10", "CVE-2021-41773", "in_progress", owner="Lab owner", note="Assigned"
    )
    tracker.update("192.0.2.10", "CVE-2021-41773", "pending_validation", note="Patched")
    item = tracker.report("2026-01-02")["findings"][0]
    assert item["owner"] == "Lab owner"
    assert item["activity"][-1]["owner"] == "Lab owner"
    tracker.update("192.0.2.10", "CVE-2021-41773", "open", owner="", note="Unassigned")
    assert tracker.report("2026-01-02")["findings"][0]["owner"] == ""


def test_scan_history_preserves_prior_evidence(tracker, tmp_path):
    tracker.ingest(FIXTURES / "nmap-before.xml", "2026-01-01", "lab")
    path = changed(tmp_path)
    path.write_text(path.read_text().replace('portid="80"', 'portid="8080"'))
    tracker.ingest(path, "2026-01-02", "lab")
    item = tracker.report("2026-01-03")["findings"][0]
    assert any("80/tcp" in e for e in item["history"][0]["evidence"])
    assert any("8080/tcp" in e for e in item["history"][1]["evidence"])


def test_greenbone_clean_rescan_validates_pending_fixes(tracker):
    first = tracker.ingest(FIXTURES / "greenbone.xml", "2026-01-01", "full-lab")
    assert first["new"] == 2
    tracker.update("192.0.2.10", "CVE-2014-0160", "pending_validation", note="Updated TLS library")
    after = tracker.ingest(
        FIXTURES / "greenbone-after.xml", "2026-01-02", "full-lab", ["192.0.2.10"]
    )
    assert after["fixed"] == 2
    assert tracker.report("2026-01-03")["summary"]["fixed"] == 2
