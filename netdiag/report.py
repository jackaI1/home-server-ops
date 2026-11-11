"""Turn analysed captures into a Markdown report a person can read.

Each capture gets a short table of totals, a list of findings that crossed a
threshold, and the busiest flows and slowest DNS answers so the reader can see
where the problem is. The findings are plain sentences because the report is
meant for the first triage step, before anyone opens Wireshark.
"""

from __future__ import annotations

from .analyze import Analysis

TOP_FLOWS = 5
TOP_DNS = 5


def findings(analysis: Analysis) -> list[str]:
    """Return one sentence for each number that crossed its threshold."""
    thr = analysis.thresholds
    out: list[str] = []
    if analysis.data_segments and analysis.retransmission_rate > thr.retransmission_rate:
        out.append(
            f"{analysis.retransmission_rate:.1%} of data segments were sent again "
            f"({analysis.retransmissions} of {analysis.data_segments}); limit is {thr.retransmission_rate:.0%}."
        )
    for flow in analysis.lossy_flows[:TOP_FLOWS]:
        out.append(
            f"Flow {flow.flow} resent {flow.retransmissions} of {flow.data_segments} data segments "
            f"({flow.retransmission_rate:.1%})."
        )
    slow_dns = analysis.slow_dns
    if slow_dns:
        worst = slow_dns[0]
        out.append(
            f"{len(slow_dns)} DNS answer(s) took longer than {thr.dns_seconds * 1000:.0f} ms; "
            f"slowest was {worst.seconds * 1000:.0f} ms for {worst.name}."
        )
    for flow in analysis.slow_flows[:TOP_FLOWS]:
        out.append(
            f"Flow {flow.flow} averaged {flow.throughput_kbps:.0f} kbit/s over {flow.duration:.1f} s "
            f"(limit {thr.slow_flow_kbps:.0f} kbit/s)."
        )
    return out


def _flow_rows(analysis: Analysis) -> list[str]:
    rows = ["| Flow | Payload | Seconds | kbit/s | Resent |", "| --- | ---: | ---: | ---: | ---: |"]
    busiest = [f for f in analysis.flows if f.payload_bytes > 0][:TOP_FLOWS]
    for flow in busiest:
        rate = f"{flow.throughput_kbps:.0f}" if flow.throughput_kbps is not None else "n/a"
        rows.append(
            f"| {flow.flow} | {flow.payload_bytes:,} B | {flow.duration:.2f} | {rate} | {flow.retransmissions} |"
        )
    return rows


def _dns_rows(analysis: Analysis) -> list[str]:
    rows = ["| Name | Answer time | Seen at (epoch) |", "| --- | ---: | ---: |"]
    for answer in sorted(analysis.dns_answers, key=lambda a: -a.seconds)[:TOP_DNS]:
        rows.append(f"| {answer.name} | {answer.seconds * 1000:.1f} ms | {answer.time:.3f} |")
    return rows


def render(analyses: list[Analysis], title: str = "Network diagnostics report") -> str:
    lines = [f"# {title}", ""]
    total_issues = 0
    for analysis in analyses:
        problems = findings(analysis)
        total_issues += len(problems)
        lines += [
            f"## {analysis.pcap}",
            "",
            "| Measure | Value |",
            "| --- | ---: |",
            f"| TCP packets | {analysis.tcp_packets:,} |",
            f"| Data segments | {analysis.data_segments:,} |",
            f"| Retransmitted segments | {analysis.retransmissions:,} ({analysis.retransmission_rate:.2%}) |",
            f"| DNS queries | {analysis.dns_queries:,} |",
            f"| DNS answers | {len(analysis.dns_answers):,} |",
            "",
        ]
        if problems:
            lines += ["**Findings**", ""] + [f"- {p}" for p in problems] + [""]
        else:
            lines += ["**Findings**", "", "- None above the limits.", ""]
        if analysis.flows:
            lines += ["**Busiest flows**", ""] + _flow_rows(analysis) + [""]
        if analysis.dns_answers:
            lines += ["**Slowest DNS answers**", ""] + _dns_rows(analysis) + [""]
    lines += [
        "---",
        "",
        f"Total findings: {total_issues}. Follow the steps in `docs/slow-transfer-runbook.md`.",
        "",
    ]
    return "\n".join(lines)
