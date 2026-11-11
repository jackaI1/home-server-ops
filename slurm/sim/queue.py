"""A small simulator of the home GPU queue, using the same rules as slurm/etc/slurm.conf.

It models, in one-minute steps:
  * partition tiers: a job in a higher-tier partition may requeue (preempt) running jobs of a lower tier
  * per-user quota: a user may hold at most `quota` GPUs at once (MaxTRESPerUser)
  * fair-share: recent GPU use lowers a user's priority, and the use decays with a half-life
  * backfill (EASY): a lower-priority job may start early only if it ends before the waiting top job could start
  * requeue: a preempted job starts again from the beginning when GPUs are free, as Slurm's REQUEUE does

All GPUs are treated as one pool. Real Slurm places jobs on individual nodes, so this is a simplification.
The point of the simulator is to check the rules, not to predict exact start times on the real machines.
"""

from dataclasses import dataclass, field


@dataclass
class Job:
    id: int
    user: str
    partition: str
    gpus: int
    duration: int          # minutes of GPU time needed
    submit: int = 0        # minute the job is submitted
    start: int = None      # minute of the latest start
    first_start: int = None
    final_start: int = None  # start of the run that completed
    end: int = None
    state: str = "PENDING"  # PENDING, RUNNING, COMPLETED
    requeues: int = 0
    wasted_gpu_minutes: int = 0


@dataclass
class Config:
    gpus: int = 4                              # total GPUs across the workstations
    tiers: dict = field(default_factory=lambda: {"review": 2, "bench": 1})
    quota: dict = field(default_factory=dict)  # user -> max GPUs held at once (default: no limit)
    default_quota: int = None
    half_life: int = 7 * 24 * 60               # fair-share decay half-life, in minutes
    max_time: dict = field(default_factory=lambda: {"review": 120, "bench": 720})


class Simulator:
    def __init__(self, config, jobs):
        self.cfg = config
        self.jobs = sorted(jobs, key=lambda j: (j.submit, j.id))
        self.free = config.gpus
        self.now = 0
        self.usage = {}          # user -> decayed GPU-minutes used (fair-share input)
        self.timeline = []       # (minute, GPUs in use)
        self.events = []         # (minute, text) for the log
        self.decay = 0.5 ** (1 / config.half_life)
        for job in self.jobs:
            if job.partition not in config.tiers:
                raise ValueError(f"unknown partition {job.partition}")
            if job.gpus > config.gpus:
                raise ValueError(f"job {job.id} asks for {job.gpus} GPUs; the cluster has {config.gpus}")
            if job.duration > config.max_time[job.partition]:
                raise ValueError(f"job {job.id} is longer than the {job.partition} time limit")

    # ----- helpers -----
    def running(self):
        return [j for j in self.jobs if j.state == "RUNNING"]

    def pending(self):
        return [j for j in self.jobs if j.state == "PENDING" and j.submit <= self.now]

    def used(self, user):
        return sum(j.gpus for j in self.running() if j.user == user)

    def quota_for(self, user):
        return self.cfg.quota.get(user, self.cfg.default_quota)

    def fits_quota(self, job):
        q = self.quota_for(job.user)
        return q is None or self.used(job.user) + job.gpus <= q

    def fairshare(self, user):
        """1.0 for a user with no recent use, lower the more GPU-minutes they have used lately."""
        return 1.0 / (1.0 + self.usage.get(user, 0.0) / 60.0)

    def priority(self, job):
        age = self.now - job.submit
        return (self.cfg.tiers[job.partition] * 1000
                + self.fairshare(job.user) * 100
                + min(age, 7 * 24 * 60) * 0.001)

    def shadow_time(self, top):
        """Earliest minute the top pending job could start if nothing new is started."""
        free = self.free
        if free >= top.gpus:
            return self.now
        ends = sorted((j.end, j.gpus) for j in self.running())
        for end, gpus in ends:
            free += gpus
            if free >= top.gpus:
                return end
        return float("inf")

    # ----- one minute -----
    def step(self):
        for job in self.running():
            if job.end <= self.now:
                job.state = "COMPLETED"
                self.free += job.gpus
                self.events.append((self.now, f"job {job.id} ({job.user}) completed"))
        for job in self.jobs:
            if job.state == "PENDING" and job.submit == self.now:
                self.events.append((self.now, f"job {job.id} ({job.user}, {job.partition}) submitted"))
        self.schedule()
        in_use = sum(j.gpus for j in self.running())
        assert self.free + in_use == self.cfg.gpus, "GPU accounting broke"
        self.timeline.append((self.now, in_use))
        for user in list(self.usage):
            self.usage[user] *= self.decay
        for job in self.running():
            self.usage[job.user] = self.usage.get(job.user, 0.0) + job.gpus
        self.now += 1

    def schedule(self):
        order = sorted(self.pending(), key=self.priority, reverse=True)
        top_blocked = None
        for job in order:
            if not self.fits_quota(job):
                continue
            if self.free >= job.gpus:
                if top_blocked is not None and self.now + job.duration > self.shadow_time(top_blocked):
                    continue  # would delay the waiting job, so it must not backfill
                self.start(job)
                continue
            if top_blocked is None:
                top_blocked = job
            if self.try_preempt(job):
                self.start(job)
                top_blocked = None if top_blocked is job else top_blocked

    def start(self, job):
        job.state = "RUNNING"
        job.start = self.now
        job.final_start = self.now
        job.end = self.now + job.duration
        if job.first_start is None:
            job.first_start = self.now
        self.free -= job.gpus
        self.events.append((self.now, f"job {job.id} ({job.user}, {job.partition}) started on {job.gpus} GPU(s)"))

    def try_preempt(self, job):
        """Requeue lower-tier running jobs, newest first, if that frees enough GPUs."""
        tier = self.cfg.tiers[job.partition]
        victims = sorted((j for j in self.running() if self.cfg.tiers[j.partition] < tier),
                         key=lambda j: j.start, reverse=True)
        freed, chosen = 0, []
        for v in victims:
            if self.free + freed >= job.gpus:
                break
            freed += v.gpus
            chosen.append(v)
        if self.free + freed < job.gpus:
            return False
        for v in chosen:
            v.wasted_gpu_minutes += (self.now - v.start) * v.gpus
            v.requeues += 1
            v.state = "PENDING"
            v.start = None
            v.end = None
            self.free += v.gpus
            self.events.append((self.now, f"job {v.id} ({v.user}) requeued to make room for job {job.id}"))
        return True

    def run(self, until=None):
        last = max(j.submit for j in self.jobs) if self.jobs else 0
        horizon = until if until is not None else last + 1
        while self.now < horizon or any(j.state != "COMPLETED" for j in self.jobs):
            self.step()
            if self.now > 100_000:
                raise RuntimeError("simulation did not finish")
        return self


def summarize(sim):
    """Occupancy, wait time and fairness per user. Wait is from submission to the run that completed."""
    done = [j for j in sim.jobs if j.state == "COMPLETED"]
    horizon = max(j.end for j in done) if done else 0
    busy = sum(g for _, g in sim.timeline)
    capacity = sim.cfg.gpus * max(horizon, 1)
    per_user = {}
    for j in done:
        u = per_user.setdefault(j.user, {"jobs": 0, "gpu_minutes": 0, "waits": [], "requeues": 0, "wasted": 0})
        u["jobs"] += 1
        u["gpu_minutes"] += j.gpus * j.duration
        u["waits"].append(j.final_start - j.submit)
        u["requeues"] += j.requeues
        u["wasted"] += j.wasted_gpu_minutes
    for u in per_user.values():
        u["mean_wait_min"] = sum(u["waits"]) / len(u["waits"])
        del u["waits"]
    means = [u["mean_wait_min"] for u in per_user.values()]
    fairness = jain(means) if means else 1.0
    return {
        "makespan_min": horizon,
        "occupancy": busy / capacity,
        "users": per_user,
        "wait_fairness_jain": fairness,
    }


def jain(values):
    """Jain's index: 1.0 when every user waits the same, lower when some users wait much longer."""
    total = sum(values)
    squares = sum(v * v for v in values)
    if squares == 0:
        return 1.0
    return (total * total) / (len(values) * squares)
