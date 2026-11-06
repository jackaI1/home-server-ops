"""Extract link evidence from headers and decoded text, without opening any URL."""

import ipaddress
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .identity import normalize_domain
from .models import Evidence, Finding, URLObservation
from .parser import ParsedEmail

URL_RE = re.compile(r'https?://[^\s<>"\x00-\x1f]+', re.I)
MAX_URLS = 200
MAX_TEXT = 1024 * 1024


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str | None]] = []
        self.active: tuple[str, list[str]] | None = None

    def finish_link(self):
        if self.active:
            self.links.append((self.active[0], "".join(self.active[1]).strip()))
            self.active = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "a":
            self.finish_link()
            if values.get("href"):
                self.active = (values["href"], [])
        elif values.get("src"):
            self.links.append((values["src"], None))
        elif tag == "form" and values.get("action"):
            self.links.append((values["action"], None))

    def handle_endtag(self, tag):
        if tag == "a":
            self.finish_link()

    def handle_data(self, data):
        if self.active:
            self.active[1].append(data)
        else:
            self.links.extend((m[0].rstrip(".,;!)"), None) for m in URL_RE.finditer(data))


def analyze_urls(email: ParsedEmail) -> tuple[list[URLObservation], list[Finding], list[str]]:
    observations: list[URLObservation] = []
    findings: list[Finding] = []
    uncertainties = [
        "URL checks are local indicators only. No links are opened, redirected, resolved or "
        "reputation-checked. Internationalized domains, IP links and HTTP can have legitimate uses."
    ]
    candidates = []
    for header in email.headers:
        candidates.extend(
            (m[0].rstrip(".,;!)"), None, header.evidence()) for m in URL_RE.finditer(header.value)
        )
    stack = [(email.message, 0)]
    part_count = 0
    while stack:
        part, depth = stack.pop()
        part_count += 1
        number = part_count
        if part_count > 200 or depth > 30:
            uncertainties.append("MIME part/depth limit reached; some content was not examined.")
            break
        if part.get_content_disposition() == "attachment" or part.get_filename():
            uncertainties.append(f"MIME part {number}: attachment content was not examined.")
            continue
        if part.get_content_type() == "message/rfc822":
            uncertainties.append(f"MIME part {number}: nested message was not examined.")
            continue
        if part.is_multipart():
            children = list(part.iter_parts())
            stack.extend((child, depth + 1) for child in reversed(children))
            continue
        if part.get_content_type() not in ("text/plain", "text/html"):
            uncertainties.append(f"MIME part {number}: non-text content was not examined.")
            continue
        try:
            text = part.get_content(errors="replace")
        except (LookupError, ValueError):
            uncertainties.append(f"MIME part {number}: unknown charset; used UTF-8 replacement.")
            text = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
        uncertainties.extend(
            f"MIME part {number} parser defect: {type(d).__name__}." for d in part.defects
        )
        if "\ufffd" in text:
            uncertainties.append(f"MIME part {number}: undecodable bytes were replaced.")
        if len(text) > MAX_TEXT:
            uncertainties.append(f"MIME part {number}: text limit reached; remainder not examined.")
            text = text[:MAX_TEXT]
        source = f"MIME part {number} (decoded {part.get_content_type()})"
        if part.get_content_type() == "text/html":
            parser = LinkParser()
            parser.feed(text)
            parser.close()
            parser.finish_link()
            links = parser.links
        else:
            links = [(m[0].rstrip(".,;!)"), None) for m in URL_RE.finditer(text)]
        candidates.extend(
            (url, visible, Evidence(source, f"URL: {url}; visible text: {visible}"))
            for url, visible in links
        )
    seen = set()
    for url, visible, evidence in candidates:
        if not re.match(r"^https?://", url, re.I) or (url, visible, evidence.source) in seen:
            continue
        seen.add((url, visible, evidence.source))
        if len(observations) >= MAX_URLS:
            uncertainties.append("URL limit (200) reached; further links were not examined.")
            break
        host = None

        def flag(code, points, summary, evidence=evidence):
            findings.append(
                Finding(
                    code,
                    points,
                    summary,
                    [evidence],
                    "Inspect the destination through a known safe process; "
                    "this structural indicator does not establish intent.",
                )
            )

        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            if not host or any(c.isspace() or ord(c) < 32 for c in host):
                raise ValueError("missing or invalid host")
            normalized = normalize_domain(host)
            if parsed.username is not None or parsed.password is not None:
                flag(
                    "url_userinfo",
                    15,
                    "URL contains user information before @; "
                    f"the actual destination host is {host}.",
                )
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                flag("url_ip_host", 10, "URL uses a literal IP address instead of a domain name.")
            if "xn--" in normalized or not host.isascii():
                flag("url_idn", 5, "URL uses an internationalized domain; inspect its spelling.")
            if parsed.scheme.lower() == "http":
                flag("url_insecure", 5, "URL uses unencrypted HTTP.")
            if visible:
                text = visible.strip()
                apparent = None
                if re.match(r"^https?://", text, re.I):
                    apparent = urlsplit(text).hostname
                elif re.fullmatch(r"[\w-]+(?:\.[\w-]+)+(?:/[^\s]*)?", text):
                    apparent = text.split("/", 1)[0]
                if apparent and normalize_domain(apparent) != normalized:
                    flag(
                        "url_text_mismatch",
                        20,
                        f"Link text suggests {apparent}, but its destination host is {host}.",
                    )
        except (ValueError, UnicodeError):
            flag("url_malformed", 5, "URL could not be parsed reliably.")
            uncertainties.append(f"Malformed URL in {evidence.source}; destination unknown.")
        observations.append(URLObservation(url, host, visible, evidence))
    return observations, findings, uncertainties
