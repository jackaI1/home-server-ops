import shutil

import pytest

from benchmarks.cli import main
from benchmarks.runner import (
    JOBS,
    RunnerError,
    RunSpec,
    Settings,
    Target,
    expand_specs,
    iter_runs,
    parse_target,
)

from .conftest import SAMPLES


def test_parse_target_needs_a_name_and_an_existing_directory(tmp_path):
    target = parse_target(f"nas={tmp_path}")
    assert target.name == "nas" and target.directory == tmp_path
    with pytest.raises(RunnerError, match="name=/path"):
        parse_target(str(tmp_path))
    with pytest.raises(RunnerError, match="does not exist"):
        parse_target(f"x={tmp_path / 'missing'}")
    with pytest.raises(RunnerError, match="letters"):
        parse_target(f"bad name={tmp_path}")


def test_grid_has_one_mix_per_mixed_job_only(tmp_path):
    specs = expand_specs(
        [Target("nas", tmp_path)],
        Settings(block_sizes=("4k", "1m"), iodepths=(1, 16), rwmix=(70, 50)),
    )
    # 4 non-mixed jobs x 2 block sizes x 2 queue depths, plus the mixed job x 2 mixes.
    assert len(specs) == 4 * 2 * 2 + 1 * 2 * 2 * 2
    mixed = [s for s in specs if s.job == "rand-mixed"]
    assert {s.rwmix for s in mixed} == {70, 50}
    assert all(s.rwmix is None for s in specs if s.job != "rand-mixed")


def test_unknown_job_is_refused(tmp_path):
    with pytest.raises(RunnerError, match="unknown job"):
        expand_specs([Target("nas", tmp_path)], Settings(jobs=("seq-read", "bogus")))


def test_repeats_run_round_robin_across_configurations(tmp_path):
    t = Target("nas", tmp_path)
    specs = [RunSpec(t, "seq-read", "1m", 1, None), RunSpec(t, "rand-read", "4k", 1, None)]
    order = [(rep, s.job) for rep, s in iter_runs(specs, 2)]
    assert order == [(1, "seq-read"), (1, "rand-read"), (2, "seq-read"), (2, "rand-read")]


def test_config_names_are_stable_and_readable(tmp_path):
    t = Target("nas", tmp_path)
    assert RunSpec(t, "rand-mixed", "4k", 16, 70).config == "rand-mixed-bs4k-qd16-mix70"
    assert RunSpec(t, "seq-write", "1m", 1, None).config == "seq-write-bs1m-qd1"


def test_all_five_job_files_exist():
    from benchmarks.runner import JOB_DIR

    assert {p.stem for p in JOB_DIR.glob("*.fio")} == set(JOBS)


def test_report_command_rebuilds_tables_from_saved_runs(sample_dir, capsys):
    assert main(["report", str(sample_dir)]) == 0
    assert (sample_dir / "summary.csv").exists()
    assert (sample_dir / "plots" / "iops.png").exists()
    assert "wrote 8 runs" in capsys.readouterr().out


def test_bad_arguments_return_an_error_code_not_a_traceback(tmp_path, capsys):
    assert main(["report", str(tmp_path)]) == 2
    assert "error:" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("fio") is None, reason="fio is not installed")
def test_real_fio_run_end_to_end_and_test_file_is_removed(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    out = tmp_path / "out"
    code = main([
        "run", "--target", f"t={target}", "--out", str(out),
        "--size", "4M", "--runtime", "1", "--ramp", "0", "--repeats", "2",
        "--jobs", "rand-read", "--block-sizes", "4k", "--iodepths", "1",
        "--ioengine", "psync", "--buffered",
    ])
    assert code == 0
    assert len(list((out / "raw" / "t").rglob("run*.json"))) == 2
    assert (out / "summary.csv").read_text().count("\n") == 2  # header + one configuration
    assert not (target / "homeops-fio-benchmark.dat").exists()
