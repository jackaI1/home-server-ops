"""The manifest records hand-labelled expectations, not generated analyzer output."""

import json
from pathlib import Path

from phish_header_analyzer.analyzer import analyze_bytes

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_synthetic_corpus_has_expected_findings_scores_and_source_lines():
    cases = json.loads((SAMPLES / "cases.json").read_text())
    assert len(cases) == 9
    for case in cases:
        raw = (SAMPLES / case["file"]).read_bytes()
        report = analyze_bytes(
            raw, trusted_authserv_ids=("mx.receiver.test",), brands={"North Bank": "bank.test"}
        )
        assert report.score == case["score"], case["file"]
        assert {f.code for f in report.findings} == set(case["findings"]), case["file"]
        assert report.uncertainties
        physical_lines = raw.decode().splitlines()
        for finding in report.findings:
            assert finding.evidence and finding.caveat
            for evidence in finding.evidence:
                if evidence.start_line is not None:
                    assert evidence.excerpt == "\n".join(
                        physical_lines[evidence.start_line - 1 : evidence.end_line]
                    )
