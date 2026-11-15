"""Command line: `python -m benchmarks run|report|compare`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .compare import DEFAULT_BW_DROP, DEFAULT_P99_RISE, compare
from .report import write_report
from .runner import (
    DEFAULT_BLOCK_SIZES,
    DEFAULT_IODEPTHS,
    DEFAULT_RWMIX,
    JOBS,
    RunnerError,
    Settings,
    parse_target,
    run_all,
)
from .parse import FioResultError


def _csv(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def _int_csv(text: str) -> list[int]:
    return [int(item) for item in _csv(text)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m benchmarks", description="Repeatable fio storage benchmarks for the NAS and local disks.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run fio on each target, then write the tables and plots")
    run.add_argument("--target", action="append", required=True, metavar="NAME=PATH",
                     help="a directory to test, e.g. nas=/mnt/nas/bench (repeat for more)")
    run.add_argument("--out", required=True, type=Path, help="folder for the results")
    run.add_argument("--size", default="1G", help="test file size per target (default 1G)")
    run.add_argument("--runtime", type=int, default=30, help="seconds per run (default 30)")
    run.add_argument("--ramp", type=int, default=2, help="warm-up seconds that are not measured")
    run.add_argument("--repeats", type=int, default=5, help="repeats per configuration (default 5)")
    run.add_argument("--jobs", type=_csv, default=list(JOBS), help="comma list: " + ",".join(JOBS))
    run.add_argument("--block-sizes", type=_csv, default=list(DEFAULT_BLOCK_SIZES), help="e.g. 4k,128k,1m")
    run.add_argument("--iodepths", type=_int_csv, default=list(DEFAULT_IODEPTHS), help="queue depths, e.g. 1,16")
    run.add_argument("--rwmix", type=_int_csv, default=list(DEFAULT_RWMIX),
                     help="read percentages for rand-mixed, e.g. 70,50")
    run.add_argument("--ioengine", default="libaio", help="fio I/O engine (default libaio, Linux)")
    run.add_argument("--buffered", action="store_true",
                     help="use the page cache (default bypasses it, so the disk is what is measured)")

    report = sub.add_parser("report", help="rebuild the CSVs and plots from saved results")
    report.add_argument("out", type=Path)

    cmp_ = sub.add_parser("compare", help="compare two result folders and flag changes")
    cmp_.add_argument("before", type=Path)
    cmp_.add_argument("after", type=Path)
    cmp_.add_argument("--bw-drop", type=float, default=DEFAULT_BW_DROP,
                      help="flag a throughput drop bigger than this percent (default 10)")
    cmp_.add_argument("--p99-rise", type=float, default=DEFAULT_P99_RISE,
                      help="flag a p99 latency rise bigger than this percent (default 20)")
    cmp_.add_argument("--allow-mismatch", action="store_true",
                      help="show numbers even when kernel, fio or filesystem differ")
    cmp_.add_argument("--markdown", type=Path, help="also write the table to this file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            targets = [parse_target(t) for t in args.target]
            settings = Settings(
                size=args.size, runtime=args.runtime, ramp=args.ramp,
                ioengine=args.ioengine, direct=not args.buffered, repeats=args.repeats,
                jobs=args.jobs, block_sizes=args.block_sizes, iodepths=args.iodepths,
                rwmix=args.rwmix,
            )
            saved = run_all(targets, settings, args.out)
            counts = write_report(args.out)
            print(f"saved {saved} runs; wrote {counts['configurations']} configurations to {args.out}/summary.csv")
            return 0
        if args.command == "report":
            counts = write_report(args.out)
            print(f"wrote {counts['runs']} runs, {counts['configurations']} configurations, {counts['plots']} plots")
            return 0
        if args.command == "compare":
            text, code = compare(args.before, args.after, bw_drop=args.bw_drop,
                                 p99_rise=args.p99_rise, allow_mismatch=args.allow_mismatch)
            print(text, end="")
            if args.markdown:
                args.markdown.write_text(text)
            return code
    except (RunnerError, FioResultError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2
