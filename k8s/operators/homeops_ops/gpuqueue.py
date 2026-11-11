"""Queue for GPU jobs with per-team quotas, in the style of Kueue.

A GPUJob says which team it belongs to, how many GPUs it needs and which image runs it.
The controller admits a job only when two limits both have room: the team's quota, and the GPUs free
in the whole cluster. Jobs that do not fit wait, with a reason and a position, in the status.
An admitted job becomes a batch Job that asks for the GPUs. A finalizer keeps a deleted GPUJob
around until its Job is removed, so nothing is left running."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import yaml

API = "homeops.local/v1alpha1"
KIND = "GPUJob"
FINALIZER = "homeops.local/gpujob-cleanup"
OWNER_LABEL = "homeops.local/gpujob"
NAME = re.compile(r"^[a-z]([-a-z0-9]{0,40}[a-z0-9])?$")


@dataclass
class Quota:
    cluster_gpus: int
    resource_name: str = "nvidia.com/gpu"
    teams: dict = field(default_factory=dict)


def load_quota(source):
    if isinstance(source, Quota):
        return source
    if isinstance(source, dict):
        data = source
    else:
        with open(source, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    cluster = data.get("clusterGPUs")
    if not isinstance(cluster, int) or cluster < 1:
        raise ValueError("clusterGPUs must be a whole number of at least 1")
    teams = data.get("teams") or {}
    for team, limit in teams.items():
        if not isinstance(limit, int) or limit < 0:
            raise ValueError(f"team {team!r} needs a whole-number GPU quota")
    return Quota(cluster_gpus=cluster, resource_name=data.get("resourceName", "nvidia.com/gpu"), teams=teams)


def _phase(job):
    return (job.get("status") or {}).get("phase", "Queued")


def _gpus(job):
    return int(job["spec"]["gpus"])


def _sort_key(job):
    meta = job["metadata"]
    return (-int(job["spec"].get("priority", 0)), meta.get("creationTimestamp", ""), meta["name"])


def job_manifest(job, quota):
    meta, spec = job["metadata"], job["spec"]
    name, namespace = meta["name"], meta["namespace"]
    container = {
        "name": "run",
        "image": spec["image"],
        "resources": {"limits": {quota.resource_name: str(_gpus(job))}},
    }
    if spec.get("command"):
        container["command"] = list(spec["command"])
    return {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": f"{name}-run", "namespace": namespace,
                     "labels": {OWNER_LABEL: name, "homeops.local/team": spec["team"]}},
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 3600,
            "template": {
                "metadata": {"labels": {OWNER_LABEL: name}},
                "spec": {"restartPolicy": "Never", "containers": [container]},
            },
        },
    }


def _now_iso(now):
    when = now or datetime.now(timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def plan(jobs, owned, quota, now=None):
    """Decide what to do. `jobs` are GPUJob dicts; `owned` maps a GPUJob name to its batch Job dict.
    Returns actions as (op, name, payload) tuples, applied in order by `apply`."""
    quota = load_quota(quota)
    stamp = _now_iso(now)
    actions = []
    live = []
    for job in jobs:
        meta = job["metadata"]
        name = meta["name"]
        finalizers = list(meta.get("finalizers") or [])
        if meta.get("deletionTimestamp"):
            if name in owned:
                actions.append(("delete_job", name, owned[name]["metadata"]["name"]))
            if FINALIZER in finalizers:
                actions.append(("set_finalizers", name, [f for f in finalizers if f != FINALIZER]))
            continue
        if FINALIZER not in finalizers:
            actions.append(("set_finalizers", name, finalizers + [FINALIZER]))
        live.append(job)
    live.sort(key=lambda j: j["metadata"].get("creationTimestamp", ""))

    team_used, cluster_used = {}, 0

    def hold(job):
        nonlocal cluster_used
        team = job["spec"]["team"]
        team_used[team] = team_used.get(team, 0) + _gpus(job)
        cluster_used += _gpus(job)

    def set_status(job, status):
        current = job.get("status") or {}
        if any(current.get(k) != v for k, v in status.items()):
            actions.append(("set_status", job["metadata"]["name"], status))

    # Jobs already admitted keep their GPUs until their batch Job finishes.
    for job in live:
        if _phase(job) != "Admitted":
            continue
        name = job["metadata"]["name"]
        run = owned.get(name)
        if run is None:
            actions.append(("create_job", name, job_manifest(job, quota)))
            hold(job)
            continue
        run_status = run.get("status") or {}
        if run_status.get("succeeded"):
            set_status(job, {**job["status"], "phase": "Succeeded", "reason": "Completed", "position": None})
        elif run_status.get("failed"):
            set_status(job, {**job["status"], "phase": "Failed", "reason": "JobFailed", "position": None})
        else:
            hold(job)

    # Then admit from the queue, highest priority and oldest first.
    waiting = sorted((j for j in live if _phase(j) == "Queued"), key=_sort_key)
    position = 0
    for job in waiting:
        name, team, gpus = job["metadata"]["name"], job["spec"]["team"], _gpus(job)
        if team not in quota.teams:
            set_status(job, {"phase": "Failed", "reason": "UnknownTeam", "position": None,
                             "message": f"team {team!r} has no quota"})
            continue
        if gpus > quota.cluster_gpus or gpus > quota.teams[team]:
            set_status(job, {"phase": "Failed", "reason": "TooLarge", "position": None,
                             "message": f"{gpus} GPUs is more than the team or cluster can ever hold"})
            continue
        if team_used.get(team, 0) + gpus > quota.teams[team]:
            reason = "TeamQuota"
        elif cluster_used + gpus > quota.cluster_gpus:
            reason = "NoFreeGPUs"
        else:
            actions.append(("create_job", name, job_manifest(job, quota)))
            set_status(job, {"phase": "Admitted", "reason": "Admitted", "position": None,
                             "jobName": f"{name}-run", "admittedAt": stamp, "message": ""})
            hold(job)
            continue
        position += 1
        set_status(job, {"phase": "Queued", "reason": reason, "position": position,
                         "message": f"waiting: {reason}"})
    return actions


def apply(kube, namespace, actions):
    for op, name, payload in actions:
        if op == "set_finalizers":
            kube.patch(API, KIND, namespace, name, {"metadata": {"finalizers": payload or None}})
        elif op == "delete_job":
            kube.delete("batch/v1", "Job", namespace, payload)
        elif op == "create_job":
            kube.create(payload)
        elif op == "set_status":
            kube.patch(API, KIND, namespace, name, {"status": payload}, status=True)
        else:
            raise ValueError(f"unknown action {op}")


def reconcile_once(kube, namespace, quota, now=None):
    jobs = kube.list(API, KIND, namespace)
    owned = {}
    for run in kube.list("batch/v1", "Job", namespace, label_selector=OWNER_LABEL):
        owned[run["metadata"]["labels"][OWNER_LABEL]] = run
    actions = plan(jobs, owned, quota, now=now)
    apply(kube, namespace, actions)
    return actions
