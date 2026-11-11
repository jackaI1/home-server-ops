"""Read a saved packet capture with tshark and report what slowed a transfer.

tshark is the command-line half of Wireshark. It reads a .pcap file and prints
the fields we ask for, one line per packet. This module turns those lines into
three answers:

* TCP retransmissions: segments the sender had to send again, usually because
  a packet was lost or a link was congested.
* DNS answer times: how long the server took to answer a name lookup.
* Per-flow throughput: how many payload bytes each TCP connection moved per
  second, so slow connections stand out.

The parsing functions take plain strings, so the unit tests can use output that
was stored earlier instead of running tshark.
"""

from __future__ import annotations

import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

TCP_FIELDS = (
    "frame.number",
    "frame.time_epoch",
    "ip.src",
    "tcp.srcport",
    "ip.dst",
    "tcp.dstport",
    "tcp.len",
)
RETRANSMISSION_FIELDS = ("frame.number",)
DNS_FIELDS = (
    "frame.time_epoch",
    "ip.src",
    "dns.flags.response",
    "dns.qry.name",
    "dns.time",
)


class AnalysisError(RuntimeError):
    """tshark is missing, or it could not read the capture."""


@dataclass(frozen=True)
class Thresholds:
    """Limits that decide when a number is flagged. Defaults suit a home LAN."""

    retransmission_rate: float = 0.01  # 1 % of data segments sent twice
    dns_seconds: float = 0.2  # answers slower than 200 ms
    slow_flow_kbps: float = 1000.0  # 1 Mbit/s
    min_flow_bytes: int = 20_000  # ignore tiny flows when judging speed


@dataclass(frozen=True)
class TcpPacket:
    number: int
    time: float
    src: str
    sport: int
    dst: str
    dport: int
    payload: int

    @property
    def flow(self) -> str:
        return f"{self.src}:{self.sport} -> {self.dst}:{self.dport}"


@dataclass(frozen=True)
class DnsAnswer:
    time: float
    client: str
    name: str
    seconds: float


@dataclass
class FlowStats:
    flow: str
    first: float
    last: float
    data_segments: int = 0
    payload_bytes: int = 0
    retransmissions: int = 0

    @property
    def duration(self) -> float:
        return self.last - self.first

    @property
    def throughput_kbps(self) -> float | None:
        """Payload kilobits per second, or None when the flow lasted no time."""
        if self.duration <= 0:
            return None
        return self.payload_bytes * 8 / 1000 / self.duration

    @property
    def retransmission_rate(self) -> float:
        return self.retransmissions / self.data_segments if self.data_segments else 0.0


@dataclass
class Analysis:
    pcap: str
    thresholds: Thresholds
    tcp_packets: int = 0
    data_segments: int = 0
    retransmissions: int = 0
    flows: list[FlowStats] = field(default_factory=list)
    dns_answers: list[DnsAnswer] = field(default_factory=list)
    dns_queries: int = 0

    @property
    def retransmission_rate(self) -> float:
        return self.retransmissions / self.data_segments if self.data_segments else 0.0

    @property
    def slow_dns(self) -> list[DnsAnswer]:
        limit = self.thresholds.dns_seconds
        return sorted((a for a in self.dns_answers if a.seconds > limit), key=lambda a: -a.seconds)

    @property
    def slow_flows(self) -> list[FlowStats]:
        limit = self.thresholds.slow_flow_kbps
        slow = [
            f for f in self.flows
            if f.payload_bytes >= self.thresholds.min_flow_bytes
            and f.throughput_kbps is not None and f.throughput_kbps < limit
        ]
        return sorted(slow, key=lambda f: f.throughput_kbps or 0.0)

    @property
    def lossy_flows(self) -> list[FlowStats]:
        return sorted(
            (f for f in self.flows if f.retransmissions and f.retransmission_rate > self.thresholds.retransmission_rate),
            key=lambda f: -f.retransmission_rate,
        )


def parse_tcp_line(line: str) -> TcpPacket | None:
    """Parse one line printed with TCP_FIELDS. Returns None for malformed lines."""
    parts = line.rstrip("\n").split("\t")
    if len(parts) < len(TCP_FIELDS):
        return None
    number, time, src, sport, dst, dport, payload = parts[: len(TCP_FIELDS)]
    try:
        return TcpPacket(
            number=int(number),
            time=float(time),
            src=src,
            sport=int(sport),
            dst=dst,
            dport=int(dport),
            payload=int(payload or 0),
        )
    except ValueError:
        return None


def parse_dns_line(line: str) -> tuple[bool, DnsAnswer | None]:
    """Parse one line printed with DNS_FIELDS.

    Returns (is_query, answer). The answer is set only for a response that
    tshark matched to its query, which is the only place it reports dns.time.
    """
    parts = line.rstrip("\n").split("\t")
    if len(parts) < len(DNS_FIELDS):
        return False, None
    time, client, response, name, seconds = parts[: len(DNS_FIELDS)]
    # tshark prints a boolean field as "True" or "False", depending on version.
    if response not in ("1", "True"):
        return True, None
    if not seconds:
        return False, None
    try:
        return False, DnsAnswer(time=float(time), client=client, name=name, seconds=float(seconds))
    except ValueError:
        return False, None


def summarize_flows(packets: list[TcpPacket], retransmitted: set[int]) -> tuple[list[FlowStats], int]:
    """Group TCP packets into flows. Returns the flows and the data-segment total."""
    flows: dict[str, FlowStats] = {}
    data_segments = 0
    for pkt in packets:
        stats = flows.get(pkt.flow)
        if stats is None:
            stats = flows[pkt.flow] = FlowStats(flow=pkt.flow, first=pkt.time, last=pkt.time)
        stats.first = min(stats.first, pkt.time)
        stats.last = max(stats.last, pkt.time)
        if pkt.payload > 0:
            stats.data_segments += 1
            stats.payload_bytes += pkt.payload
            data_segments += 1
        if pkt.number in retransmitted:
            stats.retransmissions += 1
    return sorted(flows.values(), key=lambda f: -f.payload_bytes), data_segments


def run_tshark(tshark: str, pcap: Path, display_filter: str, fields: tuple[str, ...]) -> list[str]:
    cmd = [
        tshark, "-r", str(pcap), "-n", "-Y", display_filter,
        "-T", "fields", "-E", "separator=\t", "-E", "occurrence=f",
    ]
    for name in fields:
        cmd += ["-e", name]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AnalysisError(f"tshark took longer than 15 minutes on {pcap}") from exc
    if proc.returncode != 0:
        raise AnalysisError(f"tshark failed on {pcap}: {proc.stderr.strip()[-400:]}")
    return proc.stdout.splitlines()


def find_tshark() -> str:
    found = shutil.which("tshark")
    if found is None:
        raise AnalysisError("tshark is not installed (apt install tshark, or brew install wireshark)")
    return found


def analyze(pcap: Path, thresholds: Thresholds = Thresholds(), tshark: str | None = None) -> Analysis:
    """Analyse one capture file and return the numbers the report needs."""
    pcap = Path(pcap)
    if not pcap.is_file():
        raise AnalysisError(f"capture file not found: {pcap}")
    tshark = tshark or find_tshark()

    tcp_lines = run_tshark(tshark, pcap, "tcp", TCP_FIELDS)
    packets = [p for p in (parse_tcp_line(line) for line in tcp_lines) if p is not None]
    retransmitted = {
        int(line)
        for line in run_tshark(tshark, pcap, "tcp.analysis.retransmission", RETRANSMISSION_FIELDS)
        if line.strip().isdigit()
    }
    flows, data_segments = summarize_flows(packets, retransmitted)

    dns_queries = 0
    dns_answers: list[DnsAnswer] = []
    for line in run_tshark(tshark, pcap, "dns", DNS_FIELDS):
        is_query, answer = parse_dns_line(line)
        dns_queries += is_query
        if answer is not None:
            dns_answers.append(answer)

    return Analysis(
        pcap=pcap.name,
        thresholds=thresholds,
        tcp_packets=len(packets),
        data_segments=data_segments,
        retransmissions=sum(f.retransmissions for f in flows),
        flows=flows,
        dns_answers=dns_answers,
        dns_queries=dns_queries,
    )
