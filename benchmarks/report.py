"""Write the CSV tables and plots for a result folder from its saved JSON."""

from __future__ import annotations

from pathlib import Path

from .plots import plot_all
from .summary import load_runs, summarize, write_runs_csv, write_summary_csv


def write_report(out_dir: Path) -> dict[str, int]:
    """Rebuild runs.csv, summary.csv and plots/ from raw/ and return counts."""
    rows = load_runs(out_dir)
    if not rows:
        raise FileNotFoundError(f"no saved runs under {out_dir / 'raw'}")
    write_runs_csv(rows, out_dir / "runs.csv")
    summaries = summarize(rows)
    write_summary_csv(summaries, out_dir / "summary.csv")
    plots = plot_all(rows, out_dir / "plots")
    return {"runs": len(rows), "configurations": len(summaries), "plots": len(plots)}
