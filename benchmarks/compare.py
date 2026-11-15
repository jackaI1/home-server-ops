"""Compare two saved result folders, for example last month against today.

The comparison is only fair when the kernel, the fio version, the filesystem
and the test settings match. ``check_fair`` lists every difference it finds,
and the command stops unless the person passes ``--allow-mismatch``.

A configuration is flagged when throughput drops by more than
``--bw-drop`` percent, or when p99 latency rises by more than
``--p99-rise`` percent. The flags are a prompt to look closer, not a verdict:
the spread columns say how much the numbers moved between repeats anyway.
"""

from __future__ import annotations

import json
from pathlib import Path

from .summary import load_runs, summarize

FAIR_KEYS = ("kernel", "fio_version")
FAIR_SETTINGS = ("size", "runtime_s", "ioengine", "direct")
DEFAULT_BW_DROP = 10.0
DEFAULT_P99_RISE = 20.0


def load_environment(out_dir: Path) -> dict:
    path = out_dir / "environment.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; run `python -m benchmarks run` first")
    return json.loads(path.read_text())


def check_fair(old: dict, new: dict) -> list[str]:
    """Return a list of differences that make two runs unfair to compare."""
    problems = []
    for key in FAIR_KEYS:
        if old.get(key) != new.get(key):
            problems.append(f"{key}: {old.get(key)} vs {new.get(key)}")
    for key in FAIR_SETTINGS:
        if old.get("settings", {}).get(key) != new.get("settings", {}).get(key):
            problems.append(
                f"settings.{key}: {old.get('settings', {}).get(key)} vs {new.get('settings', {}).get(key)}"
            )
    old_targets, new_targets = old.get("targets", {}), new.get("targets", {})
    for name in sorted(set(old_targets) | set(new_targets)):
        o, n = old_targets.get(name), new_targets.get(name)
        if o is None or n is None:
            problems.append(f"target {name} is in only one of the two runs")
            continue
        for key in ("fstype", "mount_options"):
            if o.get(key) != n.get(key):
                problems.append(f"target {name} {key}: {o.get(key)} vs {n.get(key)}")
        if "unknown" in (o.get("fstype"), n.get("fstype")):
            problems.append(f"target {name} filesystem type could not be read")
    return problems


def _key(summary: dict) -> tuple:
    return (summary["target"], summary["job"], summary["direction"],
            summary["block_size"], str(summary["iodepth"]), str(summary["rwmix"]))


def compare(old_dir: Path, new_dir: Path, *, bw_drop: float = DEFAULT_BW_DROP,
            p99_rise: float = DEFAULT_P99_RISE, allow_mismatch: bool = False) -> tuple[str, int]:
    """Return a Markdown report and an exit code (0 ok, 1 flagged, 2 unfair)."""
    old_env, new_env = load_environment(old_dir), load_environment(new_dir)
    problems = check_fair(old_env, new_env)
    lines = [f"# Comparison: {old_dir.name} vs {new_dir.name}", ""]
    if problems and not allow_mismatch:
        lines.append("The two runs are not comparable, so no numbers are shown:")
        lines += [f"- {p}" for p in problems]
        lines.append("")
        lines.append("Re-run with `--allow-mismatch` to see the numbers anyway.")
        return "\n".join(lines) + "\n", 2
    if problems:
        lines += ["**Warning: the runs differ, so changes may come from the setup, not the disk.**", ""]
        lines += [f"- {p}" for p in problems]
        lines.append("")

    old = {_key(s): s for s in summarize(load_runs(old_dir))}
    new = {_key(s): s for s in summarize(load_runs(new_dir))}
    shared = sorted(set(old) & set(new))
    if not shared:
        lines.append("No configuration appears in both runs.")
        return "\n".join(lines) + "\n", 2

    lines += [
        "| Target | Job | Block | Queue | Mix | Direction | Throughput before | after | change | p99 before | after | change | Flag |",
        "| --- | --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    flagged = 0
    for key in shared:
        o, n = old[key], new[key]
        bw_change = _pct(o["bw_mib_s_median"], n["bw_mib_s_median"])
        p99_change = _pct(o.get("p99_latency_us_median"), n.get("p99_latency_us_median"))
        flags = []
        if bw_change is not None and bw_change < -bw_drop:
            flags.append("slower")
        if p99_change is not None and p99_change > p99_rise:
            flags.append("latency up")
        flagged += bool(flags)
        lines.append(
            f"| {o['target']} | {o['job']} | {o['block_size']} | {o['iodepth']} | {o['rwmix'] or '-'} | "
            f"{o['direction']} | {o['bw_mib_s_median']} | {n['bw_mib_s_median']} | {_fmt(bw_change)} | "
            f"{o.get('p99_latency_us_median', '-')} | {n.get('p99_latency_us_median', '-')} | "
            f"{_fmt(p99_change)} | {', '.join(flags) or 'ok'} |"
        )
    lines += ["", f"{flagged} of {len(shared)} configurations flagged "
              f"(throughput drop over {bw_drop:g}% or p99 rise over {p99_rise:g}%)."]
    return "\n".join(lines) + "\n", (1 if flagged else 0)


def _pct(before, after) -> float | None:
    if before in (None, "", 0) or after in (None, ""):
        return None
    return (float(after) - float(before)) / float(before) * 100.0


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:+.1f}%"
