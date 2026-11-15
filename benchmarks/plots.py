"""Draw one dot plot per metric, with every repeat shown as its own dot.

Each configuration is a column on the x-axis. Each repeat is a dot, and a short
bar marks the median, so the spread between repeats is visible instead of being
hidden behind an average. Each target has its own colour, in a fixed order, so
a target keeps its colour in every chart. The y-axis is log scale because block
sizes and queue depths change the numbers by orders of magnitude.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")  # no display needed on a server or in CI
import matplotlib.pyplot as plt  # noqa: E402

from .parse import DirectionResult  # noqa: E402
from .runner import JOBS  # noqa: E402

JOB_ORDER = {job: index for index, job in enumerate(JOBS)}

# Okabe-Ito colours: distinguishable for the common colour-blind types.
# A fixed order, never cycled: a fifth target is refused instead of getting a
# generated colour that could not be told apart from the others.
TARGET_COLOURS = ("#0072B2", "#E69F00", "#009E73", "#D55E00")
INK = "#333333"
MUTED = "#6B6B6B"
GRID = "#D9D9D9"

METRICS = {
    "bw_mib_s": ("Throughput", "MiB/s"),
    "iops": ("IOPS", "operations per second"),
    "p99_latency_us": ("p99 latency", "microseconds (lower is better)"),
}


def _config_order(rows: Sequence[DirectionResult]) -> list[tuple]:
    keys = {(r.job, r.block_size, r.iodepth, r.rwmix or 0, r.direction) for r in rows}
    # Jobs in the order they run (sequential, then random), then block size, queue depth, mix.
    return sorted(keys, key=lambda k: (JOB_ORDER.get(k[0], 99), k[1], k[2], k[3], k[4]))


def _value(row: DirectionResult, metric: str) -> float | None:
    return getattr(row, metric)


def plot_metric(rows: Sequence[DirectionResult], metric: str, path: Path) -> None:
    """Save one PNG with one column per configuration and one dot per repeat."""
    targets = sorted({r.target for r in rows})
    if len(targets) > len(TARGET_COLOURS):
        raise ValueError(f"at most {len(TARGET_COLOURS)} targets can be plotted; got {len(targets)}")
    title, unit = METRICS[metric]
    configs = _config_order(rows)
    if not configs:
        raise ValueError("no rows to plot")

    width = max(8.0, 0.6 * len(configs) + 3.0)
    fig, ax = plt.subplots(figsize=(width, 5.6), dpi=120)
    offsets = _offsets(len(targets))

    for t_index, target in enumerate(targets):
        colour = TARGET_COLOURS[t_index]
        for c_index, key in enumerate(configs):
            values = [
                _value(r, metric)
                for r in rows
                if r.target == target
                and (r.job, r.block_size, r.iodepth, r.rwmix or 0, r.direction) == key
                and _value(r, metric) is not None
            ]
            if not values:
                continue
            x = c_index + offsets[t_index]
            ax.scatter([x] * len(values), values, s=22, color=colour, alpha=0.8, zorder=3, linewidths=0)
            median = statistics.median(values)
            ax.plot([x - 0.18, x + 0.18], [median, median], color=colour, linewidth=2, zorder=4)

    ax.set_yscale("log")
    ax.set_xticks(range(len(configs)))
    ax.set_xticklabels([_key_label(k) for k in configs], rotation=45, ha="right", fontsize=8, color=INK)
    ax.set_ylabel(f"{title} ({unit})", color=INK)
    ax.set_title(f"{title} across repeated runs", color=INK, loc="left", fontsize=12)
    ax.grid(axis="y", color=GRID, linewidth=0.8, which="major")
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(MUTED)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=MUTED)

    handles = [
        plt.Line2D([], [], marker="o", linestyle="", color=TARGET_COLOURS[i], label=t)
        for i, t in enumerate(targets)
    ]
    ax.legend(handles=handles, title="Target (dot = one run, bar = median)", frameon=False,
              loc="upper right", fontsize=9)

    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def _key_label(key: tuple) -> str:
    job, block_size, iodepth, rwmix, direction = key
    label = f"{job} {block_size} qd{iodepth}"
    if rwmix:
        label += f" {direction}"
    return label


def _offsets(count: int) -> list[float]:
    if count == 1:
        return [0.0]
    spread = 0.3
    step = spread / (count - 1)
    return [-spread / 2 + i * step for i in range(count)]


def plot_all(rows: Sequence[DirectionResult], out_dir: Path) -> list[Path]:
    """Write the three standard plots and return their paths."""
    written = []
    for metric in METRICS:
        usable = [r for r in rows if _value(r, metric) is not None]
        if not usable:
            continue
        path = out_dir / f"{metric}.png"
        plot_metric(usable, metric, path)
        written.append(path)
    return written
