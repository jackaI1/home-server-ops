"""Compare explicit identities, preserving ambiguity rather than choosing a sender."""

import re
import unicodedata
from email import policy
from email.headerregistry import Address

from .models import Finding, Header
from .parser import ParsedEmail


def normalize_domain(value: str) -> str:
    return value.rstrip(".").encode("idna").decode("ascii").lower()


def mailbox_domain(address: str) -> str:
    return normalize_domain(address.rsplit("@", 1)[1])


def analyze_identity(
    email: ParsedEmail,
    brands: dict[str, str],
) -> tuple[list[Finding], list[str]]:
    findings = []
    uncertainties = [
        "Domain differences are exact comparisons, not DMARC alignment. Related subdomains, "
        "bulk senders, delegated support and forwarding can legitimately use different domains. "
        "Unconfigured brand names cannot be authenticated from a display name alone."
    ]

    def single(name: str) -> tuple[Header, Address] | None:
        headers = email.all(name)
        if len(headers) != 1:
            uncertainties.append(
                f"{name}: expected one header, found {len(headers)}; identity unknown."
            )
            if len(headers) > 1:
                findings.append(
                    Finding(
                        "duplicate_identity_header",
                        10,
                        f"Multiple {name} fields make identity ambiguous.",
                        [h.evidence() for h in headers],
                        "Different mail clients may select different values; "
                        "inspect the original export.",
                    )
                )
            return None
        header = headers[0]
        if name == "Return-Path" and header.value.strip() == "<>":
            uncertainties.append(
                "Return-Path is null, which is normal for a delivery-status bounce."
            )
            return None
        try:
            parsed = policy.default.header_factory("From", header.value)
            addresses = parsed.addresses
            if parsed.defects or len(addresses) != 1 or not addresses[0].domain:
                raise ValueError("ambiguous mailbox")
            mailbox_domain(addresses[0].addr_spec)
        except (ValueError, IndexError, AttributeError, UnicodeError):
            uncertainties.append(f"{name} at line {header.start_line} has no unambiguous mailbox.")
            return None
        return header, addresses[0]

    sender = single("From")
    return_path = single("Return-Path")
    reply_to = single("Reply-To")
    if not sender:
        return findings, uncertainties
    from_header, address = sender
    from_domain = mailbox_domain(address.addr_spec)
    for target, code, points in [
        (return_path, "return_path_mismatch", 10),
        (reply_to, "reply_to_mismatch", 15),
    ]:
        if target and mailbox_domain(target[1].addr_spec) != from_domain:
            findings.append(
                Finding(
                    code,
                    points,
                    f"{target[0].name} domain differs from From ({from_domain}).",
                    [from_header.evidence(), target[0].evidence()],
                    "This can be legitimate for forwarding, support queues "
                    "or a bulk mailing service.",
                )
            )
    display = address.display_name
    apparent = re.search(r"[\w.+-]+@([\w.-]+\.[\w-]+)", display)
    apparent_domain = None
    if apparent:
        try:
            apparent_domain = normalize_domain(apparent[1])
        except UnicodeError:
            uncertainties.append(
                "The display name contains an invalid apparent email domain; "
                "that display-address comparison could not be completed."
            )
    if apparent_domain and apparent_domain != from_domain:
        findings.append(
            Finding(
                "display_address_mismatch",
                20,
                "The display name contains an email address with a different "
                "domain from the mailbox.",
                [from_header.evidence()],
                "Display names are sender-controlled; confirm the person through a known channel.",
            )
        )
    normalized_display = unicodedata.normalize("NFKC", display).casefold().strip()
    for brand, expected in brands.items():
        if (
            unicodedata.normalize("NFKC", brand).casefold().strip() == normalized_display
            and normalize_domain(expected) != from_domain
        ):
            findings.append(
                Finding(
                    "display_brand_mismatch",
                    20,
                    f"Display name {brand!r} is expected on {expected}, "
                    f"but From uses {from_domain}.",
                    [from_header.evidence()],
                    "The expected domain was supplied by the investigator; a mistaken mapping "
                    "or an authorized vendor can explain the difference.",
                )
            )
    return findings, uncertainties
