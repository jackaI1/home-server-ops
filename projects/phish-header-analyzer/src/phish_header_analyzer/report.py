"""Human and machine notes. Markdown renders untrusted material as defanged text."""

import html
import json
import re
from dataclasses import asdict

from .models import Evidence, Report


def safe_text(value: object) -> str:
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(value))
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069]", "[format-control]", text)
    text = re.sub(
        r"https?", lambda m: "hxxps" if m[0].lower() == "https" else "hxxp", text, flags=re.I
    )
    text = html.escape(text, quote=True)
    return re.sub(r"([\\`*_{}\[\]()!|#])", r"\\\1", text).replace(".", "[.]")


def evidence_line(evidence: Evidence) -> str:
    location = evidence.source
    if evidence.truncated or len(evidence.excerpt) > 1000:
        location += "; excerpt truncated, inspect original for full evidence"
    if evidence.start_line is not None:
        location += f", lines {evidence.start_line}-{evidence.end_line}"
    else:
        location += "; decoded content, no physical line attribution"
    return f"  - Evidence ({safe_text(location)}): {safe_text(evidence.excerpt[:1000])}"


def render_json(report: Report) -> str:
    return json.dumps(asdict(report), indent=2, ensure_ascii=True) + "\n"


def render_markdown(report: Report) -> str:
    lines = [
        "# Investigation note",
        "",
        f"Source: {safe_text(report.source)}",
        f"SHA-256: `{report.sha256}`",
        "",
        f"Review priority: **{report.priority}** | Score: **{report.score}/100**",
        "",
        "This score directs review. It does not determine whether an email is malicious.",
        "Each rule contributes points once; repeated evidence is retained. Total is capped at 100.",
        "",
        "## Findings",
        "",
    ]
    if not report.findings:
        lines.append("No scored indicators were found in the examined content.")
    seen = set()
    for finding in report.findings:
        points = finding.points if finding.code not in seen else 0
        seen.add(finding.code)
        lines.append(f"- **{safe_text(finding.code)} (+{points})**: {safe_text(finding.summary)}")
        lines.extend(evidence_line(e) for e in finding.evidence)
        lines.append(f"  - Context: {safe_text(finding.caveat)}")
    lines.extend(["", "## Received route (oldest to newest)", ""])
    for hop in report.received:
        lines.append(
            f"- Header #{hop.header_index}: {safe_text(hop.from_host)} to "
            f"{safe_text(hop.by_host)}; UTC {safe_text(hop.timestamp)}; "
            f"gap from previous: {hop.gap_seconds} seconds"
        )
        lines.append(evidence_line(hop.evidence))
    lines.extend(["", "## Reported authentication", ""])
    if not report.authentication:
        lines.append("No authentication claims could be read.")
    for result in report.authentication:
        trust = "configured receiver" if result.trusted else "untrusted claim"
        lines.append(
            f"- {safe_text(result.authserv_id)}: "
            f"{safe_text(result.method)}={safe_text(result.result)} "
            f"({trust}); {safe_text(result.properties)}"
        )
        lines.append(evidence_line(result.evidence))
    lines.extend(["", "## URLs examined (defanged)", ""])
    for url in report.urls:
        lines.append(f"- {safe_text(url.url)}; host: {safe_text(url.host)}")
        lines.append(evidence_line(url.evidence))
    lines.extend(["", "## Uncertainties", ""])
    lines.extend(f"- {safe_text(u)}" for u in report.uncertainties)
    lines.extend(
        [
            "",
            "## Next investigation steps",
            "",
            "- Confirm the export and receiver identity using your mail system logs.",
            "- Compare sender and reply details with a known contact through another channel.",
            "- Review destinations in an approved isolated environment; do not click from email.",
            "- Correlate the findings with message context before deciding what to do.",
            "",
        ]
    )
    return "\n".join(lines)
