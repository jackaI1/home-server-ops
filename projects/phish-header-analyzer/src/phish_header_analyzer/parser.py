"""Parse MIME without losing the physical lines of the top-level headers."""

import re
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

from .models import Header

MAX_BYTES = 10 * 1024 * 1024
MAX_HEADERS = 1000
MAX_HEADER_BYTES = 64 * 1024


@dataclass
class ParsedEmail:
    message: EmailMessage
    headers: list[Header]
    uncertainties: list[str]

    def all(self, name: str) -> list[Header]:
        return [h for h in self.headers if h.name.lower() == name.lower()]


def parse_email(raw: bytes) -> ParsedEmail:
    if len(raw) > MAX_BYTES:
        raise ValueError("Email exceeds the 10 MiB input limit")
    headers: list[Header] = []
    uncertainties = []
    for number, line in enumerate(raw.splitlines(), 1):
        if not line:
            break
        text = line.decode("utf-8", errors="replace")
        if line[:1] in (b" ", b"\t") and headers:
            header = headers[-1]
            header.value += " " + text.strip()
            header.raw += "\n" + text
            header.end_line = number
            if len(header.raw.encode("utf-8")) > MAX_HEADER_BYTES:
                raise ValueError("Header exceeds the 64 KiB limit")
        elif re.match(rb"^[!-9;-~]+:", line):
            name, value = text.split(":", 1)
            if len(line) > MAX_HEADER_BYTES:
                raise ValueError("Header exceeds the 64 KiB limit")
            headers.append(Header(name, value.strip(), text, number, number))
            if len(headers) > MAX_HEADERS:
                raise ValueError("Email exceeds the 1000 header limit")
        else:
            uncertainties.append(f"Malformed header at line {number}; header parsing stopped.")
            break
    message = BytesParser(policy=policy.default).parsebytes(raw)
    uncertainties.extend(f"Email parser defect: {type(d).__name__}." for d in message.defects)
    return ParsedEmail(message, headers, uncertainties)
