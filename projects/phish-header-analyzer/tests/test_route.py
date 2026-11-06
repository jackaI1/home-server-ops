import pytest


def parse(raw):
    from phish_header_analyzer.parser import parse_email

    return parse_email(raw)


def route(raw):
    from phish_header_analyzer.received import analyze_received

    return analyze_received(parse(raw))


def test_folded_headers_preserve_exact_evidence_and_crlf():
    email = parse(
        b"Received: from a.test\r\n\tby b.test; Tue, 03 Nov 2026 10:00:00 +0000\r\n"
        b"From: a@a.test\r\n\r\nbody\r\n"
    )
    assert len(email.headers) == 2
    evidence = email.headers[0].evidence()
    assert (evidence.start_line, evidence.end_line) == (1, 2)
    assert "\tby b.test" in evidence.excerpt
    assert email.headers[0].value == "from a.test by b.test; Tue, 03 Nov 2026 10:00:00 +0000"


def test_hops_are_oldest_first_with_timezone_aware_gap():
    hops, findings, _ = route(
        b"Received: from b.test by c.test; Tue, 03 Nov 2026 06:02:00 -0400\n"
        b"Received: from a.test by b.test; Tue, 03 Nov 2026 10:00:00 +0000\n\n"
    )
    assert [h.header_index for h in hops] == [2, 1]
    assert [h.gap_seconds for h in hops] == [None, 120]
    assert hops[0].from_host == "a.test"
    assert hops[0].by_host == "b.test"
    assert not findings


def test_negative_and_long_gaps_keep_two_source_lines():
    hops, findings, _ = route(
        b"Received: from b.test by c.test; Tue, 03 Nov 2026 12:00:00 +0000\n"
        b"Received: from a.test by b.test; Tue, 03 Nov 2026 09:59:00 +0000\n"
        b"Received: from x.test by a.test; Tue, 03 Nov 2026 10:00:00 +0000\n\n"
    )
    assert [h.gap_seconds for h in hops] == [None, -60, 7260]
    assert {f.code for f in findings} == {"received_time_reversal", "received_long_gap"}
    assert [e.start_line for e in findings[0].evidence] == [3, 2]


@pytest.mark.parametrize("stamp", ["nonsense", "Tue, 03 Nov 2026 10:00:00", ""])
def test_unusable_received_dates_are_uncertainty_not_fake_utc(stamp):
    hops, findings, uncertainties = route(f"Received: from a.test by b.test; {stamp}\n\n".encode())
    assert hops[0].timestamp is None
    assert not findings
    assert any("timestamp" in u for u in uncertainties)


def test_missing_received_and_malformed_header_are_visible():
    email = parse(b"From: a@example.test\nthis is broken\n\nbody")
    assert email.uncertainties
    _, _, uncertainties = route(b"From: a@example.test\n\nbody")
    assert any("Received" in u for u in uncertainties)


def test_no_timing_comparison_across_unparseable_hop():
    hops, findings, _ = route(
        b"Received: from b.test by c.test; Tue, 03 Nov 2026 12:00:00 +0000\n"
        b"Received: from a.test by b.test; unknown\n"
        b"Received: from x.test by a.test; Tue, 03 Nov 2026 10:00:00 +0000\n\n"
    )
    assert all(h.gap_seconds is None for h in hops)
    assert not findings
