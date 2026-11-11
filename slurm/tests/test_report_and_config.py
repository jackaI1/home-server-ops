"""Checks the report, the sacct parser, the submit script, and that the simulator agrees with slurm.conf."""

import io
import re
import subprocess
from pathlib import Path

import pytest

from slurm.sim.queue import Config
from slurm.sim.report import demo_batch, main, parse_sacct, sacct_summary

ROOT = Path(__file__).resolve().parents[1]
CONF = (ROOT / "etc" / "slurm.conf").read_text()


def parse_time(text):
    days, _, hms = text.rpartition("-") if "-" in text else ("0", "", text)
    h, m, s = (int(x) for x in hms.split(":"))
    return int(days) * 1440 + h * 60 + m + s // 60


def partitions():
    result = {}
    for line in CONF.splitlines():
        if line.startswith("PartitionName="):
            fields = dict(p.split("=", 1) for p in line.split() if "=" in p)
            result[fields["PartitionName"]] = fields
    return result


def test_simulator_tiers_match_slurm_conf():
    parts = partitions()
    cfg = Config()
    for name, fields in parts.items():
        assert cfg.tiers[name] == int(fields["PriorityTier"]), name


def test_simulator_time_limits_match_slurm_conf():
    cfg = Config()
    for name, fields in partitions().items():
        assert cfg.max_time[name] == parse_time(fields["MaxTime"]), name


def test_simulator_gpu_count_matches_the_nodes_in_slurm_conf():
    total = sum(int(m) for m in re.findall(r"Gres=gpu:(\d+)", CONF))
    assert Config().gpus == total


def test_gres_conf_lists_the_same_nodes_and_two_gpus_each():
    gres = (ROOT / "etc" / "gres.conf").read_text()
    for node in re.findall(r"NodeName=(\S+) Gres", CONF):
        assert f"NodeName={node} Name=gpu File=/dev/nvidia[0-1]" in gres


@pytest.mark.parametrize("script", ["review.sbatch", "bench.sbatch"])
def test_job_scripts_use_partitions_and_limits_from_slurm_conf(script):
    text = (ROOT / "jobs" / script).read_text()
    part = re.search(r"#SBATCH --partition=(\S+)", text).group(1)
    time_limit = re.search(r"#SBATCH --time=(\S+)", text).group(1)
    assert part in partitions()
    assert parse_time(time_limit) <= parse_time(partitions()[part]["MaxTime"])
    assert "#SBATCH --gres=gpu:1" in text and "#SBATCH --account=homelab" in text


def test_bench_jobs_can_be_requeued_and_review_jobs_are_not_preempted():
    assert "#SBATCH --requeue" in (ROOT / "jobs" / "bench.sbatch").read_text()
    assert "PreemptMode=REQUEUE" in CONF and "PreemptType=preempt/partition_prio" in CONF


def test_submit_script_dry_run_builds_one_sbatch_per_line(tmp_path):
    batch = tmp_path / "batch.txt"
    batch.write_text("# comment\n\nreview /data/a.pdf\nbench llama\n")
    out = subprocess.run(["bash", str(ROOT / "scripts" / "submit_batch.sh"), "--dry-run", str(batch)],
                         capture_output=True, text=True, check=True).stdout
    lines = out.strip().splitlines()
    assert len(lines) == 2
    assert "review.sbatch" in lines[0] and "INPUT=" in lines[0]
    assert "bench.sbatch" in lines[1] and "MODEL=llama" in lines[1]


def test_submit_script_rejects_unknown_job_kinds(tmp_path):
    batch = tmp_path / "bad.txt"
    batch.write_text("train x\n")
    result = subprocess.run(["bash", str(ROOT / "scripts" / "submit_batch.sh"), "--dry-run", str(batch)],
                            capture_output=True, text=True)
    assert result.returncode == 2 and "unknown job kind" in result.stderr


SACCT = """\
alice|2026-03-01T09:00:00|2026-03-01T09:10:00|2026-03-01T09:40:00|billing=2,cpu=4,gres/gpu=1|COMPLETED
bob|2026-03-01T09:00:00|2026-03-01T09:30:00|2026-03-01T10:30:00|billing=8,cpu=4,gres/gpu=2|COMPLETED
alice|2026-03-01T09:05:00|Unknown|Unknown|billing=2,cpu=4,gres/gpu=1|PENDING
"""


def test_sacct_parser_skips_jobs_that_never_started():
    rows = parse_sacct(SACCT)
    assert [r["user"] for r in rows] == ["alice", "bob"]
    assert rows[0]["wait"] == 10 and rows[0]["gpu_minutes"] == 30
    assert rows[1]["gpu_minutes"] == 120 and rows[1]["wait"] == 30


def test_sacct_summary_gives_per_user_numbers_and_fairness():
    summary = sacct_summary(parse_sacct(SACCT))
    assert summary["users"]["alice"]["jobs"] == 1
    assert summary["users"]["bob"]["mean_wait_min"] == 30
    assert 0 < summary["wait_fairness_jain"] <= 1


def test_report_cli_reads_sacct_file(tmp_path):
    f = tmp_path / "sacct.txt"
    f.write_text(SACCT)
    out = io.StringIO()
    assert main(["--sacct", str(f)], out=out) == 0
    assert "| bob | 1 | 120 | 30.0 |" in out.getvalue()


def test_demo_report_shows_the_quota_effect_for_the_benchmark_user():
    out = io.StringIO()
    assert main(["--demo"], out=out) == 0
    text = out.getvalue()
    assert "| carol |" in text
    assert "GPU occupancy" in text and "Wait fairness (Jain)" in text
    assert len(demo_batch()) == 16  # 12 review runs and 4 benchmarks
