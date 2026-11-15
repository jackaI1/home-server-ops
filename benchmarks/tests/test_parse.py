import copy
import json

import pytest

from benchmarks.parse import MIB, FioResultError, parse_run
from benchmarks.summary import load_runs

from .conftest import SAMPLES


def _wrapper(name="rand-read", mix=None):
    path = SAMPLES / "raw" / "mac" / f"{name}-bs4k-qd1{'-mix70' if mix else ''}" / "run01.json"
    return json.loads(path.read_text())


def test_read_job_gives_one_row_with_throughput_iops_and_p99():
    wrapper = _wrapper("rand-read")
    rows = parse_run(wrapper)

    assert [r.direction for r in rows] == ["read"]
    row = rows[0]
    read = wrapper["fio"]["jobs"][0]["read"]
    assert row.bw_mib_s == pytest.approx(read["bw_bytes"] / MIB)
    assert row.iops == pytest.approx(read["iops"])
    assert row.p99_latency_us == pytest.approx(read["clat_ns"]["percentile"]["99.000000"] / 1000)
    assert row.block_size == "4k"
    assert row.iodepth == 1
    assert row.rwmix is None
    assert row.fio_version == "fio-3.43"


def test_mixed_job_gives_a_row_for_each_direction_with_the_mix_recorded():
    rows = parse_run(_wrapper("rand-mixed", mix=True))

    assert [r.direction for r in rows] == ["read", "write"]
    assert all(r.rwmix == 70 for r in rows)


def test_older_fio_without_bw_bytes_falls_back_to_kib_per_second():
    wrapper = _wrapper("rand-read")
    read = wrapper["fio"]["jobs"][0]["read"]
    read.pop("bw_bytes")
    read["bw"] = 2048  # KiB/s
    row = parse_run(wrapper)[0]
    assert row.bw_mib_s == pytest.approx(2.0)


def test_missing_p99_is_none_not_zero():
    wrapper = _wrapper("rand-read")
    wrapper["fio"]["jobs"][0]["read"]["clat_ns"]["percentile"] = {}
    assert parse_run(wrapper)[0].p99_latency_us is None


def test_fio_error_is_refused_rather_than_compared():
    wrapper = copy.deepcopy(_wrapper("rand-read"))
    wrapper["fio"]["jobs"][0]["error"] = 5
    with pytest.raises(FioResultError, match="error 5"):
        parse_run(wrapper)


def test_run_that_moved_no_data_is_refused():
    wrapper = copy.deepcopy(_wrapper("rand-read"))
    wrapper["fio"]["jobs"][0]["read"] = {"io_bytes": 0, "total_ios": 0}
    with pytest.raises(FioResultError, match="moved no data"):
        parse_run(wrapper)


def test_missing_wrapper_fields_are_reported_clearly():
    with pytest.raises(FioResultError, match="not a benchmark run file"):
        parse_run({"fio": {}})


def test_load_runs_reads_every_saved_file():
    rows = load_runs(SAMPLES)
    # 3 configurations x 2 repeats; rand-mixed contributes two directions.
    assert len(rows) == 2 * (1 + 1 + 2)
    assert {r.target for r in rows} == {"mac"}
