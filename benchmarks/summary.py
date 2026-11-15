"""Collect saved runs into CSV tables: one row per run, and one per configuration.

The spread column is the gap between the fastest and slowest repeat, as a
percentage of the median. A small spread means the numbers can be trusted for
a comparison; a large one means the disk or the network was moving around
during the test, and a change of a few percent would not show anything real.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .parse import DirectionResult, parse_run

RUN_FIELDS = [
    "target", "job", "direction", "block_size", "iodepth", "rwmix", "repeat",
    "bw_mib_s", "iops", "p99_latency_us", "fio_version",
]
SUMMARY_FIELDS = [
    "target", "job", "direction", "block_size", "iodepth", "rwmix", "runs",
    "bw_mib_s_median", "bw_mib_s_min", "bw_mib_s_max", "bw_spread_pct",
    "iops_median", "iops_min", "iops_max", "iops_spread_pct",
    "p99_latency_us_median", "p99_latency_us_min", "p99_latency_us_max", "p99_spread_pct",
]


def load_runs(out_dir: Path) -> list[DirectionResult]:
    """Parse every saved run under ``out_dir/raw``."""
    rows: list[DirectionResult] = []
    for path in sorted((out_dir / "raw").glob("*/*/run*.json")):
        rows.extend(parse_run(json.loads(path.read_text())))
    return rows


def _spread_pct(values: list[float], median: float) -> float | None:
    if not values or median == 0:
        return None
    return (max(values) - min(values)) / median * 100.0


def group_key(row: DirectionResult) -> tuple:
    return (row.target, row.job, row.direction, row.block_size, row.iodepth, row.rwmix)


def summarize(rows: Iterable[DirectionResult]) -> list[dict]:
    """Return one summary dict per configuration, sorted for stable output."""
    groups: dict[tuple, list[DirectionResult]] = defaultdict(list)
    for row in rows:
        groups[group_key(row)].append(row)

    summaries = []
    for key in sorted(groups, key=lambda k: tuple("" if v is None else v for v in k)):
        members = groups[key]
        bw = [r.bw_mib_s for r in members]
        iops = [r.iops for r in members]
        p99 = [r.p99_latency_us for r in members if r.p99_latency_us is not None]
        bw_med = statistics.median(bw)
        iops_med = statistics.median(iops)
        row = {
            "target": key[0], "job": key[1], "direction": key[2],
            "block_size": key[3], "iodepth": key[4],
            "rwmix": "" if key[5] is None else key[5],
            "runs": len(members),
            "bw_mib_s_median": round(bw_med, 2),
            "bw_mib_s_min": round(min(bw), 2),
            "bw_mib_s_max": round(max(bw), 2),
            "bw_spread_pct": _round(_spread_pct(bw, bw_med)),
            "iops_median": round(iops_med, 1),
            "iops_min": round(min(iops), 1),
            "iops_max": round(max(iops), 1),
            "iops_spread_pct": _round(_spread_pct(iops, iops_med)),
        }
        if p99:
            p99_med = statistics.median(p99)
            row.update({
                "p99_latency_us_median": round(p99_med, 1),
                "p99_latency_us_min": round(min(p99), 1),
                "p99_latency_us_max": round(max(p99), 1),
                "p99_spread_pct": _round(_spread_pct(p99, p99_med)),
            })
        else:
            row.update({k: "" for k in SUMMARY_FIELDS if k.startswith("p99")})
        summaries.append(row)
    return summaries


def _round(value: float | None) -> float | str:
    return "" if value is None else round(value, 1)


def write_runs_csv(rows: Iterable[DirectionResult], path: Path) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=RUN_FIELDS)
        writer.writeheader()
        for r in sorted(rows, key=lambda r: (group_key(r), r.repeat)):
            writer.writerow({
                "target": r.target, "job": r.job, "direction": r.direction,
                "block_size": r.block_size, "iodepth": r.iodepth,
                "rwmix": "" if r.rwmix is None else r.rwmix, "repeat": r.repeat,
                "bw_mib_s": round(r.bw_mib_s, 2), "iops": round(r.iops, 1),
                "p99_latency_us": "" if r.p99_latency_us is None else round(r.p99_latency_us, 1),
                "fio_version": r.fio_version,
            })


def write_summary_csv(summaries: list[dict], path: Path) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(summaries)
