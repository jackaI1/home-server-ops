"""Turn queue results into a Markdown table: GPU occupancy, wait time and fairness per user.

Two inputs are supported:
  python -m slurm.sim.report --demo              simulate the mixed demo batch
  python -m slurm.sim.report --sacct FILE        read `sacct -P -n -X` output from the real cluster

The sacct command that produces FILE:
  sacct -P -n -X -a -S 2026-01-01 -o User,Submit,Start,End,AllocTRES,State
"""

import argparse
import sys
from datetime import datetime

from slurm.sim.queue import Config, Job, Simulator, jain, summarize


def demo_batch():
    """A mixed batch: short review runs from two people and long benchmarks from a third."""
    jobs, jid = [], 1
    for minute in range(0, 240, 20):
        jobs.append(Job(jid, "alice" if minute % 40 == 0 else "bob", "review", 1, 25, submit=minute))
        jid += 1
    for minute in range(0, 120, 30):
        jobs.append(Job(jid, "carol", "bench", 2, 180, submit=minute))
        jid += 1
    return jobs


def render_markdown(report):
    lines = [
        f"Makespan: {report['makespan_min']} minutes. GPU occupancy: {report['occupancy']:.0%}. "
        f"Wait fairness (Jain): {report['wait_fairness_jain']:.2f} (1.00 means every user waits the same).",
        "",
        "| User | Jobs | GPU-minutes | Mean wait (min) | Requeues | GPU-minutes lost to requeue |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for user, u in sorted(report["users"].items()):
        lines.append(f"| {user} | {u['jobs']} | {u['gpu_minutes']} | {u['mean_wait_min']:.1f} | "
                     f"{u['requeues']} | {u['wasted']} |")
    return "\n".join(lines) + "\n"


def parse_sacct(text):
    """Parse `sacct -P -n -X` lines into per-user rows: user, wait (min), GPU-minutes, state."""
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        user, submit, start, end, tres, state = line.split("|")[:6]
        if start in ("Unknown", "None", "") or end in ("Unknown", "None", ""):
            continue  # never started or still running
        fmt = "%Y-%m-%dT%H:%M:%S"
        t_submit, t_start, t_end = (datetime.strptime(x, fmt) for x in (submit, start, end))
        gpus = 0
        for part in tres.split(","):
            if part.startswith("gres/gpu="):
                gpus = int(part.split("=", 1)[1])
        minutes = (t_end - t_start).total_seconds() / 60
        rows.append({"user": user, "wait": (t_start - t_submit).total_seconds() / 60,
                     "gpu_minutes": gpus * minutes, "state": state})
    return rows


def sacct_summary(rows):
    users = {}
    for r in rows:
        u = users.setdefault(r["user"], {"jobs": 0, "gpu_minutes": 0.0, "waits": []})
        u["jobs"] += 1
        u["gpu_minutes"] += r["gpu_minutes"]
        u["waits"].append(r["wait"])
    for u in users.values():
        u["mean_wait_min"] = sum(u["waits"]) / len(u["waits"])
        del u["waits"]
    means = [u["mean_wait_min"] for u in users.values()]
    return {"makespan_min": None, "occupancy": None, "users": users,
            "wait_fairness_jain": jain(means) if means else 1.0}


def main(argv=None, out=sys.stdout):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--demo", action="store_true", help="simulate the demo batch")
    group.add_argument("--sacct", metavar="FILE", help="read sacct output from a file")
    args = parser.parse_args(argv)
    if args.demo:
        sim = Simulator(Config(gpus=4, quota={"alice": 2, "bob": 2, "carol": 2}), demo_batch()).run()
        report = summarize(sim)
    else:
        with open(args.sacct, encoding="utf-8") as fh:
            report = sacct_summary(parse_sacct(fh.read()))
    out.write(render_markdown(report) if report["occupancy"] is not None else _table_only(report))
    return 0


def _table_only(report):
    lines = [f"Wait fairness (Jain): {report['wait_fairness_jain']:.2f}", "",
             "| User | Jobs | GPU-minutes | Mean wait (min) |", "|---|---:|---:|---:|"]
    for user, u in sorted(report["users"].items()):
        lines.append(f"| {user} | {u['jobs']} | {u['gpu_minutes']:.0f} | {u['mean_wait_min']:.1f} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
