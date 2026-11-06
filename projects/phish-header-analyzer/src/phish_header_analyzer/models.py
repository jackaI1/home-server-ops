"""Serializable observations, with provenance kept next to each claim."""

from dataclasses import dataclass, field


@dataclass
class Evidence:
    source: str
    excerpt: str
    start_line: int | None = None
    end_line: int | None = None
    truncated: bool = False

    def __post_init__(self):
        # One source can support many observations. Bound repeated serialized copies.
        if len(self.excerpt) > 4096:
            self.excerpt = self.excerpt[:4096]
            self.truncated = True


@dataclass
class Header:
    name: str
    value: str
    raw: str
    start_line: int
    end_line: int

    def evidence(self) -> Evidence:
        return Evidence(self.name, self.raw, self.start_line, self.end_line)


@dataclass
class Finding:
    code: str
    points: int
    summary: str
    evidence: list[Evidence]
    caveat: str


@dataclass
class Hop:
    header_index: int
    from_host: str | None
    by_host: str | None
    timestamp: str | None
    gap_seconds: float | None
    evidence: Evidence


@dataclass
class AuthResult:
    authserv_id: str
    method: str
    result: str
    properties: dict[str, str]
    trusted: bool
    evidence: Evidence


@dataclass
class URLObservation:
    url: str
    host: str | None
    visible_text: str | None
    evidence: Evidence


@dataclass
class Report:
    source: str
    sha256: str
    score: int
    priority: str
    findings: list[Finding]
    uncertainties: list[str]
    received: list[Hop] = field(default_factory=list)
    authentication: list[AuthResult] = field(default_factory=list)
    urls: list[URLObservation] = field(default_factory=list)
    schema_version: int = 1
