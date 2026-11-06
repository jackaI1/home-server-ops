"""Read receiver-reported authentication; do not perform live verification."""

import authres

from .models import AuthResult, Finding
from .parser import ParsedEmail

FAIL_WEIGHTS = {"spf": 10, "dkim": 15, "dmarc": 25}
MAX_AUTH_RESULTS = 100
KNOWN_RESULTS = {
    "pass",
    "fail",
    "softfail",
    "neutral",
    "none",
    "temperror",
    "permerror",
    "policy",
    "hardfail",
}


def analyze_authentication(
    email: ParsedEmail,
    trusted_authserv_ids: tuple[str, ...] = (),
) -> tuple[list[AuthResult], list[Finding], list[str]]:
    trusted_ids = {name.lower().rstrip(".") for name in trusted_authserv_ids}
    results = []
    findings = []
    incomplete = False
    uncertainties = [
        "SPF, DKIM and DMARC values are saved receiver claims. No DNS lookup, "
        "signature verification or DMARC alignment calculation is performed. "
        "A configured receiver ID is only trustworthy if the export came from that receiver "
        "and it removed externally supplied claims with its own ID."
    ]
    for header in email.all("Authentication-Results"):
        if len(results) >= MAX_AUTH_RESULTS:
            incomplete = True
            break
        try:
            parsed = authres.AuthenticationResultsHeader.parse(
                "Authentication-Results: " + header.value
            )
        except (ValueError, authres.core.AuthResError, RecursionError) as error:
            uncertainties.append(
                f"Could not parse Authentication-Results at line {header.start_line} "
                f"({type(error).__name__}); do not infer a pass."
            )
            continue
        trusted = parsed.authserv_id.lower().rstrip(".") in trusted_ids
        if not trusted:
            uncertainties.append(
                f"Authentication-Results at line {header.start_line} is untrusted; "
                "its claims do not contribute points."
            )
        for item in parsed.results:
            if len(results) >= MAX_AUTH_RESULTS:
                incomplete = True
                break
            result = AuthResult(
                parsed.authserv_id,
                item.method.lower(),
                item.result.lower(),
                {f"{p.type}.{p.name}": p.value for p in item.properties},
                trusted,
                header.evidence(),
            )
            results.append(result)
            if result.result in {"temperror", "permerror", "none", "neutral", "policy"}:
                uncertainties.append(
                    f"{result.method}={result.result} at line {header.start_line} "
                    "does not establish authentication success or malicious intent."
                )
            elif result.result not in KNOWN_RESULTS:
                uncertainties.append(f"Unknown authentication result {result.result!r}.")
    if incomplete:
        uncertainties.append(
            "Authentication result limit (100) reached; some claims were not examined. "
            "No authentication failure points assigned because a later pass may be missing."
        )
        return results, findings, uncertainties
    for method, points in FAIL_WEIGHTS.items():
        claims = [r for r in results if r.method == method and r.trusted]
        if not claims:
            uncertainties.append(f"No usable trusted {method} result is available.")
            continue
        statuses = {r.result for r in claims}
        if "pass" in statuses:
            if method != "dkim" and len(statuses) > 1:
                uncertainties.append(
                    f"Trusted {method} claims are conflicting; "
                    "compare receiver logs before relying "
                    "on them. No failure points assigned."
                )
            continue
        failures = [r for r in claims if r.result in {"fail", "hardfail"}]
        code = f"auth_{method}_fail"
        if not failures and method == "spf":
            failures = [r for r in claims if r.result == "softfail"]
            points, code = 5, "auth_spf_softfail"
        if failures:
            findings.append(
                Finding(
                    code,
                    points,
                    f"The configured receiver reports {method}={failures[0].result}.",
                    [r.evidence for r in failures],
                    "Forwarding, mailing lists and configuration errors can cause authentication "
                    "failures; the result alone does not establish phishing.",
                )
            )
    return results, findings, uncertainties
