import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def analyze(raw, **kwargs):
    from phish_header_analyzer.analyzer import analyze_bytes

    return analyze_bytes(raw, **kwargs)


def cli(*args):
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    return subprocess.run(
        [sys.executable, "-m", "phish_header_analyzer", *map(str, args)],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def test_html_link_text_deception_keeps_decoded_part_provenance():
    raw = (
        b"From: a@bank.test\nContent-Type: text/html; charset=utf-8\n"
        b"Content-Transfer-Encoding: quoted-printable\n\n"
        b'<a href=3D"https://collector.test/login?x=3D1&amp;y=3D2">https://bank.test</a>'
    )
    report = analyze(raw)
    finding = next(f for f in report.findings if f.code == "url_text_mismatch")
    assert finding.points == 20
    assert finding.evidence[0].source == "MIME part 1 (decoded text/html)"
    assert finding.evidence[0].start_line is None
    assert report.urls[0].url == "https://collector.test/login?x=1&y=2"
    assert report.urls[0].visible_text == "https://bank.test"


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("https://bank.test@collect.test/login", "url_userinfo"),
        ("http://192.0.2.8/login", "url_ip_host"),
        ("https://[2001:db8::1]/login", "url_ip_host"),
        ("https://xn--bcher-kva.test/login", "url_idn"),
        ("https://bücher.test/login", "url_idn"),
        ("http://portal.test/", "url_insecure"),
        ("https://[bad/", "url_malformed"),
    ],
)
def test_url_indicators(url, code):
    report = analyze(
        f"From: a@example.test\nContent-Type: text/plain; charset=utf-8\n\nSee {url}".encode()
    )
    assert code in {f.code for f in report.findings}


def test_header_url_is_analyzed_with_physical_lines():
    report = analyze(b"From: a@example.test\nList-Unsubscribe: <http://192.0.2.1/off>\n\nHello")
    finding = next(f for f in report.findings if f.code == "url_ip_host")
    assert finding.evidence[0].start_line == 2


def test_multipart_base64_and_attachments_are_handled_without_executing():
    raw = (
        b"From: a@example.test\nMIME-Version: 1.0\n"
        b"Content-Type: multipart/mixed; boundary=x\n\n--x\n"
        b"Content-Type: text/plain\nContent-Transfer-Encoding: base64\n\n"
        b"aHR0cDovLzE5Mi4wLjIuMS8=\n--x\nContent-Type: text/html\n"
        b'Content-Disposition: attachment; filename="ignore.html"\n\n'
        b'<a href="http://198.51.100.1/">x</a>\n--x--\n'
    )
    report = analyze(raw)
    assert [u.url for u in report.urls] == ["http://192.0.2.1/"]
    assert any("attachment" in u.lower() for u in report.uncertainties)


def test_unknown_charset_and_malformed_html_do_not_crash():
    report = analyze(
        b"Content-Type: text/html; charset=unknown-charset\n\n"
        b'<a href="http://192.0.2.1/">https://bank.test'
    )
    assert report.urls
    assert any("charset" in u.lower() for u in report.uncertainties)


def test_report_hash_score_deduplication_and_no_verdict():
    raw = b"From: a@example.test\n\n" + b"http://192.0.2.1/ " * 20
    report = analyze(raw, source="test.eml")
    assert report.sha256 == hashlib.sha256(raw).hexdigest()
    assert report.source == "test.eml"
    assert report.score == 15  # insecure 5 + IP host 10, counted once per rule
    assert report.priority == "routine"
    assert any("not a probability" in u.lower() for u in report.uncertainties)


def test_markdown_defangs_links_and_escapes_hostile_text():
    from phish_header_analyzer.report import render_markdown

    report = analyze(
        b"From: <a@example.test>\nReply-To: <x@else.test>\n\nhttp://192.0.2.1/\x1b[31m",
        source="<script>evil</script>",
    )
    note = render_markdown(report)
    assert "hxxp" in note and "192[.]0[.]2[.]1" in note
    assert "http://" not in note and "https://" not in note
    assert "<script>" not in note and "\x1b" not in note
    assert "SHA-256" in note and "line" in note and "Uncertainties" in note


def test_cli_json_and_markdown_output_and_no_overwrite(tmp_path):
    sample = tmp_path / "mail.eml"
    sample.write_bytes(b"From: a@example.test\n\nhttp://192.0.2.1/")
    result = cli(sample, "--format", "json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["schema_version"] == 1 and data["score"] == 15
    target = tmp_path / "note.md"
    assert cli(sample, "-o", target).returncode == 0
    assert "Investigation note" in target.read_text()
    assert cli(sample, "-o", target).returncode == 2
    assert cli(sample, "-o", sample).returncode == 2
    assert sample.read_bytes().startswith(b"From:")


def test_cli_errors_are_concise_and_trust_and_brand_options_work(tmp_path):
    assert cli(tmp_path / "missing.eml").returncode == 2
    sample = tmp_path / "mail.eml"
    sample.write_bytes(
        b"Authentication-Results: mx.receiver.test; dmarc=fail\nFrom: North Bank <a@else.test>\n\n"
    )
    result = cli(
        sample,
        "--format",
        "json",
        "--trusted-authserv-id",
        "mx.receiver.test",
        "--brand",
        "North Bank=bank.test",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["score"] == 45
    invalid = cli(sample, "--brand", "bad")
    assert invalid.returncode == 2 and "Traceback" not in invalid.stderr


def test_limits_and_empty_input_are_explicit(tmp_path):
    with pytest.raises(ValueError, match="10 MiB"):
        analyze(b"x" * (10 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="1000 header"):
        analyze(b"X-Header: x\n" * 1001 + b"\n")
    with pytest.raises(ValueError, match="64 KiB"):
        analyze(b"X-Header: " + b"x" * 65536 + b"\n\n")
    report = analyze(b"")
    assert report.score == 0 and report.uncertainties
    target = tmp_path / "huge.eml"
    with target.open("wb") as handle:
        handle.truncate(10 * 1024 * 1024 + 1)
    result = cli(target)
    assert result.returncode == 2 and "10 MiB" in result.stderr


def test_url_limit_is_disclosed():
    report = analyze(
        b"From: a@example.test\n\n"
        + " ".join(f"https://host.test/{i}" for i in range(205)).encode()
    )
    assert len(report.urls) == 200
    assert any("URL limit" in u for u in report.uncertainties)
