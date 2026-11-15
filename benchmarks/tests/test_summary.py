import csv
import dataclasses

from benchmarks.parse import DirectionResult
from benchmarks.summary import (
    RUN_FIELDS,
    SUMMARY_FIELDS,
    load_runs,
    summarize,
    write_runs_csv,
    write_summary_csv,
)

from .conftest import SAMPLES


def _row(repeat, bw, iops=1000.0, p99=100.0):
    return DirectionResult(
        target="nas", job="seq-read", direction="read", block_size="1m", iodepth=16,
        rwmix=None, repeat=repeat, bw_mib_s=bw, iops=iops, p99_latency_us=p99,
        fio_version="fio-3.36",
    )


def test_spread_is_range_as_percent_of_median():
    # median 100, range 80..120 -> spread 40%
    rows = [_row(1, 80.0), _row(2, 100.0), _row(3, 120.0)]
    [summary] = summarize(rows)
    assert summary["runs"] == 3
    assert summary["bw_mib_s_median"] == 100.0
    assert summary["bw_mib_s_min"] == 80.0
    assert summary["bw_mib_s_max"] == 120.0
    assert summary["bw_spread_pct"] == 40.0


def test_configurations_are_kept_apart():
    rows = [_row(1, 100.0), dataclasses.replace(_row(1, 50.0), block_size="4k")]
    summaries = summarize(rows)
    assert len(summaries) == 2
    assert sorted(s["block_size"] for s in summaries) == ["1m", "4k"]


def test_missing_p99_leaves_latency_columns_empty():
    [summary] = summarize([_row(1, 10.0, p99=None), _row(2, 12.0, p99=None)])
    assert summary["p99_latency_us_median"] == ""
    assert summary["p99_spread_pct"] == ""


def test_csv_writers_use_the_documented_columns(tmp_path):
    rows = load_runs(SAMPLES)
    runs_csv = tmp_path / "runs.csv"
    summary_csv = tmp_path / "summary.csv"
    write_runs_csv(rows, runs_csv)
    write_summary_csv(summarize(rows), summary_csv)

    with runs_csv.open() as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == RUN_FIELDS
        assert len(list(reader)) == len(rows)
    with summary_csv.open() as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == SUMMARY_FIELDS
        data = list(reader)
    assert len(data) == 4  # rand-read, rand-write, rand-mixed read and write
    assert all(int(r["runs"]) == 2 for r in data)
