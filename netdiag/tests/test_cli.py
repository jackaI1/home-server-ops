"""Command-line tests: exit codes and the files the commands write."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from netdiag.__main__ import main

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
needs_tshark = pytest.mark.skipif(shutil.which("tshark") is None, reason="tshark is not installed")


@needs_tshark
def test_analyze_exit_code_follows_findings(tmp_path):
    report = tmp_path / "report.md"
    out_json = tmp_path / "findings.json"
    slow = main(["analyze", str(SAMPLES / "slow-transfer.pcap"), "--report", str(report),
                 "--json", str(out_json), "--fail-on-issues"])
    assert slow == 1
    assert "## slow-transfer.pcap" in report.read_text()
    data = json.loads(out_json.read_text())
    assert data[0]["retransmissions"] == 3
    assert data[0]["findings"]

    clean = main(["analyze", str(SAMPLES / "clean-transfer.pcap"), "--fail-on-issues"])
    assert clean == 0


@needs_tshark
def test_analyze_without_fail_flag_always_exits_zero():
    assert main(["analyze", str(SAMPLES / "slow-transfer.pcap")]) == 0


@needs_tshark
def test_thresholds_can_be_relaxed_from_the_command_line():
    code = main(["analyze", str(SAMPLES / "slow-transfer.pcap"), "--fail-on-issues",
                 "--retrans-limit", "0.5", "--dns-ms", "1000", "--slow-kbps", "1"])
    assert code == 0


def test_missing_capture_is_a_tool_error_not_a_crash(tmp_path, capsys):
    code = main(["analyze", str(tmp_path / "missing.pcap")])
    assert code == 2
    assert "capture file not found" in capsys.readouterr().err


def test_help_mentions_all_three_commands(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    text = capsys.readouterr().out
    for word in ("capture", "analyze", "run"):
        assert word in text
