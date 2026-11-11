"""Command-line entry point: python -m netdiag {capture,analyze,run} ...

capture  record packets with tcpdump while a command runs
analyze  read saved .pcap files with tshark and write a report
run      do both, then write the report next to the capture

Exit codes: 0 means the command succeeded and no findings were raised (or
--fail-on-issues was not given); 1 means --fail-on-issues was given and the
report has findings, or the command failed; 2 means the tools could not run.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .analyze import AnalysisError, Thresholds, analyze
from .capture import DEFAULT_FILTER, CaptureError, CaptureSpec, run_capture
from .report import findings, render


def _thresholds(args: argparse.Namespace) -> Thresholds:
    return Thresholds(
        retransmission_rate=args.retrans_limit,
        dns_seconds=args.dns_ms / 1000,
        slow_flow_kbps=args.slow_kbps,
    )


def _add_thresholds(parser: argparse.ArgumentParser) -> None:
    defaults = Thresholds()
    parser.add_argument("--retrans-limit", type=float, default=defaults.retransmission_rate,
                        help="flag when this share of data segments is resent (default 0.01)")
    parser.add_argument("--dns-ms", type=float, default=defaults.dns_seconds * 1000,
                        help="flag DNS answers slower than this many ms (default 200)")
    parser.add_argument("--slow-kbps", type=float, default=defaults.slow_flow_kbps,
                        help="flag flows slower than this many kbit/s (default 1000)")


def _analyse_all(pcaps: list[Path], thresholds: Thresholds):
    return [analyze(p, thresholds) for p in pcaps]


def _write_outputs(analyses, report_path: Path | None, json_path: Path | None) -> None:
    text = render(analyses)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text)
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [{"pcap": a.pcap, "findings": findings(a), "retransmission_rate": a.retransmission_rate,
                    "data_segments": a.data_segments, "retransmissions": a.retransmissions,
                    "dns_answers": [asdict(d) for d in a.dns_answers]} for a in analyses]
        json_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(text)


def cmd_capture(args: argparse.Namespace) -> int:
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    spec = CaptureSpec(iface=args.iface, out_dir=Path(args.out), bpf=args.filter)
    return run_capture(command, spec)


def cmd_analyze(args: argparse.Namespace) -> int:
    analyses = _analyse_all([Path(p) for p in args.pcaps], _thresholds(args))
    _write_outputs(analyses, Path(args.report) if args.report else None,
                   Path(args.json) if args.json else None)
    has_findings = any(findings(a) for a in analyses)
    return 1 if (args.fail_on_issues and has_findings) else 0


def cmd_run(args: argparse.Namespace) -> int:
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    out = Path(args.out)
    spec = CaptureSpec(iface=args.iface, out_dir=out, bpf=args.filter)
    code = run_capture(command, spec)
    analyses = _analyse_all([spec.pcap], _thresholds(args))
    _write_outputs(analyses, out / "report.md", out / "report.json")
    if code != 0:
        print(f"command exited with {code}; the capture is in {out}", file=sys.stderr)
        return 1
    return 1 if (args.fail_on_issues and any(findings(a) for a in analyses)) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="netdiag", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    cap = sub.add_parser("capture", help="record packets while a command runs")
    cap.add_argument("--iface", required=True, help="interface to record, for example eth0")
    cap.add_argument("--out", required=True, help="folder for capture.pcap and logs")
    cap.add_argument("--filter", default=DEFAULT_FILTER, help="tcpdump filter (default: TCP and DNS)")
    cap.add_argument("command", nargs=argparse.REMAINDER, help="the command to run after -- ")
    cap.set_defaults(func=cmd_capture)

    ana = sub.add_parser("analyze", help="analyse saved .pcap files")
    ana.add_argument("pcaps", nargs="+")
    ana.add_argument("--report", help="write the Markdown report here")
    ana.add_argument("--json", help="write findings as JSON here")
    ana.add_argument("--fail-on-issues", action="store_true", help="exit 1 if any finding is raised")
    _add_thresholds(ana)
    ana.set_defaults(func=cmd_analyze)

    run = sub.add_parser("run", help="capture a command, then analyse the capture")
    run.add_argument("--iface", required=True)
    run.add_argument("--out", required=True, help="folder for the capture, logs and report")
    run.add_argument("--filter", default=DEFAULT_FILTER)
    run.add_argument("--fail-on-issues", action="store_true")
    run.add_argument("command", nargs=argparse.REMAINDER)
    _add_thresholds(run)
    run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (AnalysisError, CaptureError) as exc:
        print(f"netdiag: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
