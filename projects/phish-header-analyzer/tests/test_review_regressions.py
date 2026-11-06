"""Concrete hostile-input and ordinary nested-MIME regressions from review."""

from phish_header_analyzer.analyzer import analyze_bytes
from phish_header_analyzer.report import render_json, render_markdown


def test_invalid_domain_in_display_name_does_not_abort_other_checks():
    report = analyze_bytes(b'From: "support@bank..test" <bad@evil.test>\n\nhttp://192.0.2.1/')
    assert "url_ip_host" in {f.code for f in report.findings}
    assert any("display" in u.lower() and "invalid" in u.lower() for u in report.uncertainties)


def test_authentication_claim_flood_is_bounded_and_disclosed():
    raw = b"Authentication-Results: mx.receiver.test; " + b"; ".join([b"spf=fail"] * 1000) + b"\n\n"
    report = analyze_bytes(raw, trusted_authserv_ids=("mx.receiver.test",))
    assert len(report.authentication) == 100
    assert any("authentication result limit" in u.lower() for u in report.uncertainties)
    assert report.authentication[0].evidence.truncated
    assert len(report.authentication[0].evidence.excerpt) == 4096
    assert len(render_json(report)) < 1_000_000
    assert "truncated" in render_markdown(report).lower()


def test_nested_mime_parts_have_distinct_provenance_even_for_identical_urls():
    raw = (
        b"Content-Type: multipart/mixed; boundary=outer\n\n"
        b"--outer\nContent-Type: multipart/alternative; boundary=inner\n\n"
        b"--inner\nContent-Type: text/plain\n\nhttps://example.test/\n--inner--\n"
        b"--outer\nContent-Type: text/plain\n\nhttps://example.test/\n--outer--\n"
    )
    report = analyze_bytes(raw)
    assert [u.url for u in report.urls] == ["https://example.test/", "https://example.test/"]
    assert [u.evidence.source for u in report.urls] == [
        "MIME part 3 (decoded text/plain)",
        "MIME part 4 (decoded text/plain)",
    ]
