"""Interpret relay timestamps without treating the trace as authenticated."""

import re
from datetime import UTC
from email.utils import parsedate_to_datetime

from .models import Finding, Hop
from .parser import ParsedEmail


def analyze_received(email: ParsedEmail) -> tuple[list[Hop], list[Finding], list[str]]:
    headers = email.all("Received")
    findings: list[Finding] = []
    uncertainties = [
        "Received fields can be forged before a trusted receiver; clock skew and queues "
        "can explain timing anomalies. Host names are reported claims, not verified infrastructure."
    ]
    if not headers:
        uncertainties.append("No Received fields: the transport route is unavailable.")
    hops = []
    previous_time = None
    previous_header = None
    for index, header in reversed(list(enumerate(headers, 1))):
        timestamp = None
        try:
            stamp = header.value.rsplit(";", 1)[1]
            timestamp = parsedate_to_datetime(stamp.strip())
            if timestamp.tzinfo is None:
                timestamp = None
            else:
                timestamp = timestamp.astimezone(UTC)
        except (ValueError, TypeError, IndexError, OverflowError):
            pass
        if timestamp is None:
            uncertainties.append(f"Received #{index} has no usable timezone-aware timestamp.")
        gap = None
        if timestamp is not None and previous_time is not None:
            gap = (timestamp - previous_time).total_seconds()
            evidence = [previous_header.evidence(), header.evidence()]
            if gap < 0:
                findings.append(
                    Finding(
                        "received_time_reversal",
                        10,
                        f"Received #{index} is {abs(gap):g} seconds earlier "
                        "than the preceding hop.",
                        evidence,
                        "Clock skew, a bad timestamp or forged trace can cause this.",
                    )
                )
            elif gap > 3600:
                findings.append(
                    Finding(
                        "received_long_gap",
                        5,
                        f"Received #{index} follows a {gap:g} second delay (over one hour).",
                        evidence,
                        "Mail queues and forwarding can legitimately delay delivery.",
                    )
                )
        hosts = {}
        for keyword in ("from", "by"):
            match = re.search(r"\b" + keyword + r"\s+([^\s();]+)", header.value, re.I)
            hosts[keyword] = match[1] if match else None
        hops.append(
            Hop(
                index,
                hosts["from"],
                hosts["by"],
                timestamp.isoformat() if timestamp else None,
                gap,
                header.evidence(),
            )
        )
        previous_time, previous_header = timestamp, header
    return hops, findings, uncertainties
