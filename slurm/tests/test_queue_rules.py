"""Tests of the queue rules against the simulator: quotas, preemption, backfill and fair-share."""

import pytest

from slurm.sim.queue import Config, Job, Simulator, jain, summarize


def run(cfg, jobs):
    return Simulator(cfg, jobs).run()


def by_id(sim):
    return {j.id: j for j in sim.jobs}


def test_quota_caps_how_many_gpus_one_user_holds():
    # Alice may hold 2 GPUs at once. The cluster has 4 free, so only the quota can hold her back.
    cfg = Config(gpus=4, quota={"alice": 2})
    sim = run(cfg, [Job(1, "alice", "bench", 1, 60), Job(2, "alice", "bench", 1, 60),
                    Job(3, "alice", "bench", 1, 60)])
    jobs = by_id(sim)
    assert jobs[1].start == 0 and jobs[2].start == 0
    assert jobs[3].start == 60, "the third GPU must wait for the quota, not for the cluster"


def test_quota_does_not_block_another_user():
    cfg = Config(gpus=4, quota={"alice": 1})
    sim = run(cfg, [Job(1, "alice", "bench", 1, 60), Job(2, "alice", "bench", 1, 60),
                    Job(3, "bob", "bench", 1, 60)])
    assert by_id(sim)[3].start == 0


def test_review_job_requeues_benchmark_when_gpus_are_full():
    cfg = Config(gpus=2)
    sim = run(cfg, [Job(1, "alice", "bench", 2, 120, submit=0), Job(2, "bob", "review", 1, 10, submit=5)])
    jobs = by_id(sim)
    assert jobs[2].start == 5, "the review must not wait behind the benchmark"
    assert jobs[1].requeues == 1
    assert jobs[1].wasted_gpu_minutes == 5 * 2, "the 5 minutes already run are lost"
    assert jobs[1].final_start == 15, "the benchmark runs again after the review finishes"
    assert jobs[1].state == "COMPLETED"


def test_lower_tier_job_never_preempts_a_higher_tier_job():
    cfg = Config(gpus=1)
    sim = run(cfg, [Job(1, "bob", "review", 1, 30, submit=0), Job(2, "alice", "bench", 1, 10, submit=5)])
    jobs = by_id(sim)
    assert jobs[1].requeues == 0 and jobs[1].start == 0
    assert jobs[2].start == 30


def test_preemption_only_requeues_as_many_jobs_as_needed():
    cfg = Config(gpus=3)
    sim = run(cfg, [Job(1, "alice", "bench", 1, 120, submit=0), Job(2, "alice", "bench", 1, 120, submit=0),
                    Job(3, "alice", "bench", 1, 120, submit=0), Job(4, "bob", "review", 1, 10, submit=5)])
    jobs = by_id(sim)
    assert sum(j.requeues for j in jobs.values()) == 1, "one GPU is enough for the review"
    assert jobs[4].start == 5


def test_backfill_runs_a_short_job_in_the_gap_without_delaying_the_big_one():
    cfg = Config(gpus=4)
    sim = run(cfg, [
        Job(1, "alice", "bench", 3, 60, submit=0),       # uses 3 of 4 GPUs until minute 60
        Job(2, "bob", "bench", 4, 30, submit=1),         # needs the whole cluster, waits until minute 60
        Job(3, "carol", "bench", 1, 30, submit=2),       # fits now and ends before minute 60: backfills
    ])
    jobs = by_id(sim)
    assert jobs[3].start == 2
    assert jobs[2].start == 60, "the waiting 4-GPU job must start when the first job ends"


def test_backfill_does_not_start_a_job_that_would_run_past_the_waiting_job():
    cfg = Config(gpus=4)
    sim = run(cfg, [
        Job(1, "alice", "bench", 3, 60, submit=0),
        Job(2, "bob", "bench", 4, 30, submit=1),
        Job(3, "carol", "bench", 1, 120, submit=2),      # would still be running at minute 60: not allowed
    ])
    jobs = by_id(sim)
    assert jobs[3].start >= 60
    assert jobs[2].start == 60


def test_fair_share_lets_the_user_with_less_recent_use_go_first():
    cfg = Config(gpus=1, half_life=60 * 24)
    sim = run(cfg, [
        Job(1, "heavy", "bench", 1, 300, submit=0),      # heavy user uses the only GPU for 5 hours
        Job(2, "heavy", "bench", 1, 60, submit=310),
        Job(3, "light", "bench", 1, 60, submit=310),
    ])
    jobs = by_id(sim)
    assert jobs[3].start < jobs[2].start


def test_gpu_accounting_never_goes_negative_or_over_capacity():
    cfg = Config(gpus=2)
    jobs = [Job(i, f"u{i % 3}", "review" if i % 2 else "bench", 1 + i % 2, 20 + i, submit=i) for i in range(1, 25)]
    sim = run(cfg, [j for j in jobs if j.gpus <= cfg.gpus])
    assert all(0 <= used <= cfg.gpus for _, used in sim.timeline)


def test_summary_reports_occupancy_wait_and_fairness():
    cfg = Config(gpus=2)
    sim = run(cfg, [Job(1, "alice", "bench", 2, 60, submit=0), Job(2, "bob", "bench", 2, 60, submit=0)])
    report = summarize(sim)
    assert report["makespan_min"] == 120
    assert report["occupancy"] == pytest.approx(1.0, abs=0.01)
    assert report["users"]["alice"]["mean_wait_min"] == 0
    assert report["users"]["bob"]["mean_wait_min"] == 60
    assert report["wait_fairness_jain"] == pytest.approx(jain([0, 60]))


def test_jain_index_is_one_for_equal_waits():
    assert jain([5, 5, 5]) == pytest.approx(1.0)
    assert jain([0, 0]) == 1.0


def test_rejects_jobs_the_cluster_or_partition_cannot_run():
    with pytest.raises(ValueError, match="asks for"):
        Simulator(Config(gpus=2), [Job(1, "a", "bench", 3, 10)])
    with pytest.raises(ValueError, match="time limit"):
        Simulator(Config(gpus=2), [Job(1, "a", "review", 1, 500)])
    with pytest.raises(ValueError, match="unknown partition"):
        Simulator(Config(gpus=2), [Job(1, "a", "nope", 1, 10)])
