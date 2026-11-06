"""Combine independent observations into a reproducible investigation report."""

import hashlib

from .authentication import analyze_authentication
from .identity import analyze_identity
from .models import Report
from .parser import parse_email
from .received import analyze_received
from .urls import analyze_urls


def analyze_bytes(
    raw: bytes,
    *,
    source: str = "<bytes>",
    trusted_authserv_ids: tuple[str, ...] = (),
    brands: dict[str, str] | None = None,
) -> Report:
    email = parse_email(raw)
    received, route_findings, route_uncertainty = analyze_received(email)
    authentication, auth_findings, auth_uncertainty = analyze_authentication(
        email, trusted_authserv_ids
    )
    identity_findings, identity_uncertainty = analyze_identity(email, brands or {})
    urls, url_findings, url_uncertainty = analyze_urls(email)
    findings = route_findings + auth_findings + identity_findings + url_findings
    # Repeated evidence should not inflate the score. Each rule contributes its maximum once.
    contributions = {}
    for finding in findings:
        contributions[finding.code] = max(contributions.get(finding.code, 0), finding.points)
    score = min(100, sum(contributions.values()))
    priority = "high" if score >= 50 else "elevated" if score >= 20 else "routine"
    uncertainties = list(
        dict.fromkeys(
            [
                "The 0-100 score is a review-priority heuristic, not a probability or verdict. "
                "A score of zero does not prove safety. Missing data adds uncertainty, not points.",
                *email.uncertainties,
                *route_uncertainty,
                *auth_uncertainty,
                *identity_uncertainty,
                *url_uncertainty,
            ]
        )
    )
    return Report(
        source,
        hashlib.sha256(raw).hexdigest(),
        score,
        priority,
        findings,
        uncertainties,
        received,
        authentication,
        urls,
    )
