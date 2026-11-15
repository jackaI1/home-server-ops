import json

from benchmarks.cli import main
from benchmarks.compare import check_fair, compare, load_environment

from .conftest import SAMPLES


def _env(**overrides):
    env = json.loads((SAMPLES / "environment.json").read_text())
    env.update(overrides)
    return env


def _known_fs_env():
    env = _env()
    for target in env["targets"].values():
        target["fstype"] = "apfs"
        target["mount_options"] = "rw"
    return env


def test_identical_environments_are_fair():
    assert check_fair(_known_fs_env(), _known_fs_env()) == []


def test_different_kernel_or_fio_is_reported():
    problems = check_fair(_env(), _env(kernel="6.8.0", fio_version="fio-3.36"))
    assert any(p.startswith("kernel:") for p in problems)
    assert any(p.startswith("fio_version:") for p in problems)


def test_different_filesystem_is_reported():
    new = _env()
    new["targets"]["mac"]["fstype"] = "ext4"
    problems = check_fair(_env(), new)
    assert any("fstype" in p for p in problems)


def test_unknown_filesystem_counts_as_a_problem():
    problems = check_fair(_env(), _env())
    assert any("could not be read" in p for p in problems)  # the Mac sample has no findmnt


def test_refuses_unfair_comparison_without_the_flag(sample_dir, tmp_path):
    other = tmp_path / "other"
    (other / "raw").mkdir(parents=True)
    (other / "environment.json").write_text(json.dumps(_env(kernel="5.15.0")))
    text, code = compare(sample_dir, other)
    assert code == 2
    assert "not comparable" in text


def test_flags_a_slower_run_and_a_latency_rise(sample_dir, tmp_path):
    # Copy the sample, then make every rand-read run 30% slower with 40% more p99.
    slower = tmp_path / "slower"
    (slower / "raw").mkdir(parents=True)
    (slower / "environment.json").write_text((sample_dir / "environment.json").read_text())
    for path in (sample_dir / "raw" / "mac" / "rand-read-bs4k-qd1").glob("run*.json"):
        wrapper = json.loads(path.read_text())
        read = wrapper["fio"]["jobs"][0]["read"]
        read["bw_bytes"] = int(read["bw_bytes"] * 0.7)
        read["iops"] = read["iops"] * 0.7
        pct = read["clat_ns"]["percentile"]
        pct["99.000000"] = pct["99.000000"] * 1.4
        target = slower / "raw" / "mac" / "rand-read-bs4k-qd1"
        target.mkdir(parents=True, exist_ok=True)
        (target / path.name).write_text(json.dumps(wrapper))
    for name in ("rand-write-bs4k-qd1", "rand-mixed-bs4k-qd1-mix70"):
        src = sample_dir / "raw" / "mac" / name
        dst = slower / "raw" / "mac" / name
        dst.mkdir(parents=True)
        for f in src.glob("run*.json"):
            (dst / f.name).write_text(f.read_text())

    text, code = compare(sample_dir, slower, allow_mismatch=True)
    assert code == 1
    assert "Warning" not in text or "differ" in text
    rand_read = [line for line in text.splitlines() if "| rand-read |" in line]
    assert rand_read and "slower" in rand_read[0] and "latency up" in rand_read[0]
    assert "rand-write" in text and "| ok |" in text


def test_missing_environment_file_says_how_to_fix_it(tmp_path):
    try:
        load_environment(tmp_path)
    except FileNotFoundError as exc:
        assert "python -m benchmarks run" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_cli_compare_exit_codes(sample_dir, capsys):
    assert main(["compare", str(sample_dir), str(sample_dir)]) == 2  # unknown fs on the Mac sample
    assert main(["compare", str(sample_dir), str(sample_dir), "--allow-mismatch"]) == 0
