import pytest


def auth(raw, trusted=()):
    from phish_header_analyzer.authentication import analyze_authentication
    from phish_header_analyzer.parser import parse_email

    return analyze_authentication(parse_email(raw), trusted)


def identity(raw, brands=None):
    from phish_header_analyzer.identity import analyze_identity
    from phish_header_analyzer.parser import parse_email

    return analyze_identity(parse_email(raw), brands or {})


def test_auth_comments_quoted_semicolons_and_repeated_dkim():
    results, findings, _ = auth(
        b"Authentication-Results: mx.receiver.test;\n"
        b' spf=pass (nested (spf=fail)) smtp.mailfrom="sender@example.test";\n'
        b' dkim=fail reason="old; key" header.d=other.test;\n'
        b" dkim=pass header.d=example.test; dmarc=pass header.from=example.test\n\n",
        ("mx.receiver.test",),
    )
    assert [r.result for r in results] == ["pass", "fail", "pass", "pass"]
    assert results[0].properties == {"smtp.mailfrom": "sender@example.test"}
    assert all(r.trusted for r in results)
    assert not findings  # One valid DKIM signature can coexist with a failed signature.
    assert results[0].evidence.end_line == 4


def test_untrusted_auth_cannot_influence_score_and_trust_matches_exactly():
    raw = (
        b"Authentication-Results: mx.receiver.test.evil.test; spf=fail; dmarc=fail\n"
        b"Authentication-Results: mx.receiver.test; dmarc=fail header.from=example.test\n\n"
    )
    results, findings, uncertainties = auth(raw)
    assert not any(r.trusted for r in results)
    assert not findings
    assert any("untrusted" in u.lower() for u in uncertainties)
    results, findings, _ = auth(raw, ("MX.RECEIVER.TEST",))
    assert [r.trusted for r in results] == [False, False, True]
    assert [(f.code, f.points) for f in findings] == [("auth_dmarc_fail", 25)]
    assert findings[0].evidence[0].start_line == 2


def test_missing_malformed_and_error_results_are_uncertainty():
    _, findings, uncertainties = auth(
        b"Authentication-Results: broken @@; dmarc=pass\n"
        b"Authentication-Results: mx.receiver.test; spf=temperror; dkim=permerror\n\n",
        ("mx.receiver.test",),
    )
    assert not findings
    assert any("parse" in u.lower() for u in uncertainties)
    assert any("temperror" in u for u in uncertainties)
    assert any("dmarc" in u for u in uncertainties)


def test_spf_softfail_and_dkim_failure_have_separate_weights():
    _, findings, _ = auth(
        b"Authentication-Results: mx.receiver.test; spf=softfail; dkim=fail\n\n",
        ("mx.receiver.test",),
    )
    assert {(f.code, f.points) for f in findings} == {
        ("auth_spf_softfail", 5),
        ("auth_dkim_fail", 15),
    }


def test_conflicting_dmarc_claims_are_disclosed():
    _, findings, uncertainties = auth(
        b"Authentication-Results: mx.receiver.test; dmarc=pass; dmarc=fail\n\n",
        ("mx.receiver.test",),
    )
    assert not findings
    assert any("conflicting" in u.lower() for u in uncertainties)


def test_sender_mismatches_have_both_headers_as_evidence():
    findings, _ = identity(
        b"From: Accounts <billing@bank.test>\nReturn-Path: <bounce@mailer.test>\n"
        b"Reply-To: collect@unrelated.test\n\n"
    )
    assert {f.code for f in findings} == {"return_path_mismatch", "reply_to_mismatch"}
    reply = next(f for f in findings if f.code == "reply_to_mismatch")
    assert [e.start_line for e in reply.evidence] == [1, 3]
    assert "legitimate" in reply.caveat.lower()


def test_case_trailing_dot_and_idna_normalization_avoid_false_mismatch():
    findings, _ = identity(
        "From: A <a@bücher.test>\nReturn-Path: <b@XN--BCHER-KVA.TEST.>\n"
        "Reply-To: c@bücher.test\n\n".encode()
    )
    assert not findings


def test_suffix_lookalike_is_not_same_domain():
    findings, _ = identity(b"From: a@bank.test\nReply-To: a@bank.test.evil.test\n\n")
    assert "reply_to_mismatch" in {f.code for f in findings}


def test_null_return_path_is_normal_for_bounces():
    findings, uncertainties = identity(b"From: postmaster@example.test\nReturn-Path: <>\n\n")
    assert not findings
    assert any("null" in u.lower() for u in uncertainties)


@pytest.mark.parametrize(
    "headers",
    [
        b"From: a@one.test\nFrom: b@two.test\n",
        b"From: a@one.test, b@two.test\n",
        b"From: not an address\n",
        b"",
    ],
)
def test_ambiguous_from_is_not_silently_selected(headers):
    findings, uncertainties = identity(headers + b"Reply-To: c@three.test\n\n")
    assert any("From" in u for u in uncertainties)
    assert "reply_to_mismatch" not in {f.code for f in findings}


def test_encoded_display_mailbox_spoof_and_explicit_brand_expectation():
    findings, _ = identity(b"From: =?UTF-8?Q?security=40bank.test?= <attacker@elsewhere.test>\n\n")
    assert "display_address_mismatch" in {f.code for f in findings}
    findings, _ = identity(
        b"From: North Bank <attacker@elsewhere.test>\n\n", {"North Bank": "bank.test"}
    )
    assert "display_brand_mismatch" in {f.code for f in findings}
    findings, _ = identity(b"From: North Bank <attacker@elsewhere.test>\n\n")
    assert "display_brand_mismatch" not in {f.code for f in findings}
