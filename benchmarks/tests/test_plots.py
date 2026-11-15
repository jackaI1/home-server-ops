import dataclasses

import pytest

from benchmarks.plots import TARGET_COLOURS, plot_all, plot_metric
from benchmarks.summary import load_runs

from .conftest import SAMPLES

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def test_plot_all_writes_three_png_files_from_saved_runs(tmp_path):
    rows = load_runs(SAMPLES)
    paths = plot_all(rows, tmp_path / "plots")

    assert sorted(p.name for p in paths) == ["bw_mib_s.png", "iops.png", "p99_latency_us.png"]
    for path in paths:
        data = path.read_bytes()
        assert data.startswith(PNG_SIGNATURE)
        assert len(data) > 5000


def test_plot_skips_metrics_with_no_values(tmp_path):
    rows = [dataclasses.replace(r, p99_latency_us=None) for r in load_runs(SAMPLES)]
    paths = plot_all(rows, tmp_path)
    assert "p99_latency_us.png" not in {p.name for p in paths}


def test_a_fifth_target_is_refused_instead_of_getting_a_colour_that_looks_the_same(tmp_path):
    base = load_runs(SAMPLES)
    rows = []
    for index in range(len(TARGET_COLOURS) + 1):
        for row in base:
            rows.append(dataclasses.replace(row, target=f"t{index}"))
    with pytest.raises(ValueError, match="at most"):
        plot_metric(rows, "bw_mib_s", tmp_path / "x.png")


def test_empty_input_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="no rows"):
        plot_metric([], "bw_mib_s", tmp_path / "x.png")
