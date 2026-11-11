"""Reconciliation tests for the GPU job queue: admission against team quota and cluster capacity,
status and reasons, finalizers on delete, and recovery when a batch Job is lost or fails."""

from datetime import datetime, timezone

import pytest

from homeops_ops import gpuqueue
from homeops_ops.gpuqueue import API, FINALIZER, KIND, OWNER_LABEL
from tests.fake_kube import FakeKube

NS = "gpu-jobs"
QUOTA = {"clusterGPUs": 2, "resourceName": "nvidia.com/gpu", "teams": {"vision": 1, "benchmarks": 2}}
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def gpujob(name, team, gpus=1, created="2026-11-11T10:00:00Z", priority=0, deleting=False, status=None,
           finalizers=True):
    meta = {"name": name, "namespace": NS, "creationTimestamp": created}
    if finalizers:
        meta["finalizers"] = [FINALIZER]
    if deleting:
        meta["deletionTimestamp"] = "2026-11-11T11:00:00Z"
    obj = {"apiVersion": API, "kind": KIND, "metadata": meta,
           "spec": {"team": team, "gpus": gpus, "image": "bench:1", "priority": priority,
                    "command": ["python", "bench.py"]}}
    if status is not None:
        obj["status"] = status
    return obj


def run_job(name, succeeded=0, failed=0):
    return {"apiVersion": "batch/v1", "kind": "Job",
            "metadata": {"name": f"{name}-run", "namespace": NS, "labels": {OWNER_LABEL: name}},
            "spec": {}, "status": {"succeeded": succeeded, "failed": failed}}


def phases(actions):
    return {name: p["phase"] for op, name, p in actions if op == "set_status"}


def created_jobs(actions):
    return [name for op, name, _ in actions if op == "create_job"]


def test_admits_up_to_the_team_quota_and_queues_the_rest():
    jobs = [gpujob("a", "vision", created="2026-11-11T10:00:00Z"),
            gpujob("b", "vision", created="2026-11-11T10:01:00Z")]
    actions = gpuqueue.plan(jobs, {}, QUOTA, now=NOW)
    assert created_jobs(actions) == ["a"]
    statuses = {name: p for op, name, p in actions if op == "set_status"}
    assert statuses["a"]["phase"] == "Admitted" and statuses["a"]["jobName"] == "a-run"
    assert statuses["b"]["phase"] == "Queued" and statuses["b"]["reason"] == "TeamQuota"
    assert statuses["b"]["position"] == 1


def test_cluster_capacity_limits_teams_together():
    # Benchmarks may hold 2 GPUs, but the cluster only has 2 in total, and vision already holds one.
    jobs = [gpujob("v", "vision"), gpujob("bench1", "benchmarks", created="2026-11-11T10:05:00Z"),
            gpujob("bench2", "benchmarks", created="2026-11-11T10:06:00Z")]
    owned = {"v": run_job("v")}
    jobs[0]["status"] = {"phase": "Admitted", "jobName": "v-run"}
    actions = gpuqueue.plan(jobs, owned, QUOTA, now=NOW)
    assert created_jobs(actions) == ["bench1"]
    queued = {n: p for op, n, p in actions if op == "set_status" and p["phase"] == "Queued"}
    assert queued["bench2"]["reason"] == "NoFreeGPUs"


def test_priority_beats_age_within_the_queue():
    jobs = [gpujob("old", "benchmarks", created="2026-11-11T09:00:00Z"),
            gpujob("urgent", "benchmarks", created="2026-11-11T11:00:00Z", priority=10)]
    actions = gpuqueue.plan(jobs, {}, QUOTA, now=NOW)
    assert created_jobs(actions)[0] == "urgent"


def test_finished_job_frees_its_gpus_for_the_queue_in_the_same_pass():
    jobs = [gpujob("first", "vision", status={"phase": "Admitted", "jobName": "first-run"}),
            gpujob("next", "vision", created="2026-11-11T10:30:00Z")]
    owned = {"first": run_job("first", succeeded=1)}
    actions = gpuqueue.plan(jobs, owned, QUOTA, now=NOW)
    assert phases(actions)["first"] == "Succeeded"
    assert created_jobs(actions) == ["next"]


def test_failed_run_marks_the_job_failed_and_frees_the_quota():
    jobs = [gpujob("broken", "vision", status={"phase": "Admitted", "jobName": "broken-run"})]
    actions = gpuqueue.plan(jobs, {"broken": run_job("broken", failed=1)}, QUOTA, now=NOW)
    assert phases(actions)["broken"] == "Failed"


def test_admitted_job_whose_batch_job_disappeared_gets_it_back():
    jobs = [gpujob("lost", "vision", status={"phase": "Admitted", "jobName": "lost-run"})]
    actions = gpuqueue.plan(jobs, {}, QUOTA, now=NOW)
    assert created_jobs(actions) == ["lost"]


def test_new_job_gets_the_finalizer_before_anything_else():
    jobs = [gpujob("fresh", "vision", finalizers=False)]
    actions = gpuqueue.plan(jobs, {}, QUOTA, now=NOW)
    assert actions[0] == ("set_finalizers", "fresh", [FINALIZER])


def test_deleting_a_job_removes_its_batch_job_and_then_the_finalizer():
    jobs = [gpujob("gone", "vision", deleting=True, status={"phase": "Admitted", "jobName": "gone-run"})]
    owned = {"gone": run_job("gone")}
    actions = gpuqueue.plan(jobs, owned, QUOTA, now=NOW)
    assert actions == [("delete_job", "gone", "gone-run"), ("set_finalizers", "gone", [])]


def test_deleting_a_queued_job_does_not_admit_it_or_its_gpus():
    jobs = [gpujob("doomed", "vision", deleting=True), gpujob("waiting", "vision", created="2026-11-11T10:02:00Z")]
    actions = gpuqueue.plan(jobs, {}, QUOTA, now=NOW)
    assert created_jobs(actions) == ["waiting"]


def test_unknown_team_fails_and_oversized_request_fails():
    jobs = [gpujob("stray", "nobody"), gpujob("huge", "vision", gpus=3, created="2026-11-11T10:01:00Z")]
    actions = gpuqueue.plan(jobs, {}, QUOTA, now=NOW)
    statuses = {n: p for op, n, p in actions if op == "set_status"}
    assert statuses["stray"]["reason"] == "UnknownTeam"
    assert statuses["huge"]["reason"] == "TooLarge"
    assert created_jobs(actions) == []


def test_status_is_only_written_when_it_changes():
    jobs = [gpujob("steady", "vision", status={"phase": "Queued", "reason": "NoFreeGPUs", "position": 1,
                                               "message": "waiting: NoFreeGPUs"})]
    jobs[0]["spec"]["team"] = "vision"
    owned = {}
    # Fill the cluster so "steady" really is waiting for free GPUs.
    filler = [gpujob("f1", "benchmarks", status={"phase": "Admitted", "jobName": "f1-run"}),
              gpujob("f2", "benchmarks", status={"phase": "Admitted", "jobName": "f2-run"})]
    owned = {"f1": run_job("f1"), "f2": run_job("f2")}
    actions = gpuqueue.plan(filler + jobs, owned, QUOTA, now=NOW)
    assert not [a for a in actions if a[0] == "set_status" and a[1] == "steady"]


def test_load_quota_rejects_bad_numbers():
    with pytest.raises(ValueError):
        gpuqueue.load_quota({"clusterGPUs": 0, "teams": {}})
    with pytest.raises(ValueError):
        gpuqueue.load_quota({"clusterGPUs": 2, "teams": {"vision": -1}})


def test_batch_job_has_the_gpu_limit_and_the_owner_label():
    quota = gpuqueue.load_quota(QUOTA)
    job = gpujob("bench", "benchmarks", gpus=2)
    manifest = gpuqueue.job_manifest(job, quota)
    container = manifest["spec"]["template"]["spec"]["containers"][0]
    assert container["resources"]["limits"] == {"nvidia.com/gpu": "2"}
    assert container["command"] == ["python", "bench.py"]
    assert manifest["metadata"]["labels"][OWNER_LABEL] == "bench"
    assert manifest["spec"]["template"]["spec"]["restartPolicy"] == "Never"


def test_reconcile_once_drives_the_fake_cluster_through_the_whole_lifecycle():
    kube = FakeKube()
    for obj in [gpujob("a", "vision", finalizers=False), gpujob("b", "vision", created="2026-11-11T10:01:00Z",
                                                              finalizers=False)]:
        kube.create(obj)

    gpuqueue.reconcile_once(kube, NS, QUOTA, now=NOW)
    a = kube.get(API, KIND, NS, "a")
    b = kube.get(API, KIND, NS, "b")
    assert a["metadata"]["finalizers"] == [FINALIZER]
    assert a["status"]["phase"] == "Admitted"
    assert b["status"]["phase"] == "Queued"
    assert kube.get("batch/v1", "Job", NS, "a-run") is not None

    # The batch Job finishes. The next pass marks "a" Succeeded and admits "b".
    kube.store[("batch/v1", "Job", NS, "a-run")]["status"] = {"succeeded": 1}
    gpuqueue.reconcile_once(kube, NS, QUOTA, now=NOW)
    assert kube.get(API, KIND, NS, "a")["status"]["phase"] == "Succeeded"
    assert kube.get(API, KIND, NS, "b")["status"]["phase"] == "Admitted"

    # Delete "b" while it runs: its Job goes, then the finalizer goes, then the object is gone.
    kube.store[(API, KIND, NS, "b")]["metadata"]["deletionTimestamp"] = "2026-11-11T12:05:00Z"
    gpuqueue.reconcile_once(kube, NS, QUOTA, now=NOW)
    assert kube.get("batch/v1", "Job", NS, "b-run") is None
    assert kube.get(API, KIND, NS, "b")["metadata"].get("finalizers") in (None, [])
