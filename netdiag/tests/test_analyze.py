"""Unit tests for the tshark parsing and flow maths, using stored sample captures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from netdiag.analyze import (
    TCP_FIELDS,
    AnalysisError,
    FlowStats,
    Thresholds,
    TcpPacket,
    analyze,
    parse_dns_line,
    parse_tcp_line,
    summarize_flows,
)
from netdiag.report import findings, render

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
needs_tshark = pytest.mark.skipif(shutil.which("tshark") is None, reason="tshark is not installed")


def test_parse_tcp_line_reads_every_field():
    line = "12\t1767000000.25\t192.168.1.20\t50001\t192.168.1.10\t22\t1000"
    pkt = parse_tcp_line(line)
    assert pkt == TcpPacket(12, 1767000000.25, "192.168.1.20", 50001, "192.168.1.10", 22, 1000)
    assert pkt.flow == "192.168.1.20:50001 -> 192.168.1.10:22"


def test_parse_tcp_line_treats_empty_payload_as_zero():
    pkt = parse_tcp_line("3\t1.0\t10.0.0.1\t1\t10.0.0.2\t2\t")
    assert pkt is not None and pkt.payload == 0


@pytest.mark.parametrize("line", ["", "1\t2.0\t10.0.0.1", "x\t1.0\t10.0.0.1\t1\t10.0.0.2\t2\t5"])
def test_parse_tcp_line_rejects_short_or_garbled_lines(line):
    assert parse_tcp_line(line) is None


def test_parse_dns_line_query_is_not_an_answer():
    is_query, answer = parse_dns_line("1.0\t192.168.1.20\t0\tsync.home.arpa\t")
    assert is_query and answer is None


def test_parse_dns_line_response_with_time_is_an_answer():
    is_query, answer = parse_dns_line("1.45\t192.168.1.20\t1\tbackup.home.arpa\t0.45")
    assert not is_query
    assert answer is not None and answer.name == "backup.home.arpa" and answer.seconds == pytest.approx(0.45)


def test_parse_dns_line_response_without_matched_query_has_no_time():
    assert parse_dns_line("1.45\t192.168.1.20\t1\tbackup.home.arpa\t") == (False, None)


def test_summarize_flows_counts_bytes_and_retransmissions():
    packets = [
        TcpPacket(1, 0.0, "a", 1, "b", 2, 0),       # handshake, no payload
        TcpPacket(2, 1.0, "a", 1, "b", 2, 1000),
        TcpPacket(3, 2.0, "a", 1, "b", 2, 1000),    # retransmitted below
        TcpPacket(4, 3.0, "a", 1, "b", 2, 1000),
        TcpPacket(5, 0.5, "c", 9, "d", 4, 500),
    ]
    flows, data_segments = summarize_flows(packets, retransmitted={3})
    by_flow = {f.flow: f for f in flows}
    slow = by_flow["a:1 -> b:2"]
    assert data_segments == 4
    assert slow.payload_bytes == 3000
    assert slow.data_segments == 3
    assert slow.retransmissions == 1
    assert slow.duration == pytest.approx(3.0)
    assert slow.throughput_kbps == pytest.approx(3000 * 8 / 1000 / 3.0)
    assert flows[0].flow == "a:1 -> b:2"  # busiest flow first


def test_flow_with_zero_duration_has_no_throughput():
    flow = FlowStats(flow="x", first=5.0, last=5.0, payload_bytes=100)
    assert flow.throughput_kbps is None
    assert flow.retransmission_rate == 0.0


def test_analyze_reports_missing_file_clearly(tmp_path):
    with pytest.raises(AnalysisError, match="not found"):
        analyze(tmp_path / "nope.pcap", tshark="/bin/echo")


def test_analyze_reports_missing_tshark(monkeypatch):
    monkeypatch.setattr("netdiag.analyze.shutil.which", lambda name: None)
    with pytest.raises(AnalysisError, match="tshark is not installed"):
        analyze(SAMPLES / "clean-transfer.pcap")


@needs_tshark
def test_slow_transfer_sample_is_caught():
    result = analyze(SAMPLES / "slow-transfer.pcap")
    assert result.retransmissions == 3
    backup = [f for f in result.flows if f.flow.endswith("-> 192.168.1.10:22")][0]
    assert backup.retransmissions == 3
    assert backup.throughput_kbps < 1000
    assert [f.flow for f in result.slow_flows] == [backup.flow]
    assert len(result.slow_dns) == 1
    assert result.slow_dns[0].name == "backup.home.arpa"
    assert result.slow_dns[0].seconds == pytest.approx(0.45, abs=0.001)
    assert result.dns_queries == 2


@needs_tshark
def test_clean_transfer_sample_has_no_findings():
    result = analyze(SAMPLES / "clean-transfer.pcap")
    assert result.retransmissions == 0
    assert result.slow_dns == []
    assert result.slow_flows == []
    assert findings(result) == []


@needs_tshark
def test_custom_thresholds_change_what_is_flagged():
    strict = Thresholds(dns_seconds=0.001)
    result = analyze(SAMPLES / "clean-transfer.pcap", thresholds=strict)
    assert len(result.slow_dns) == 2


@needs_tshark
def test_report_names_the_slow_items():
    text = render([analyze(SAMPLES / "slow-transfer.pcap")])
    assert "## slow-transfer.pcap" in text
    assert "resent 3 of 33" in text
    assert "450 ms" in text
    assert "kbit/s" in text
    assert "docs/slow-transfer-runbook.md" in text
    assert "Total findings: 4" in text


def test_tcp_fields_are_what_the_parser_expects():
    assert len(TCP_FIELDS) == 7
