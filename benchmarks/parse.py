"""Read the JSON that fio writes and pull out the three numbers we compare.

fio writes one JSON document per run. Each job has a "read" and a "write"
section, even when only one direction was used, so a direction counts only
when it moved some data. From each direction we take:

- throughput in MiB/s (fio's bw_bytes, or bw in KiB/s for older fio versions)
- IOPS (completed operations per second)
- p99 completion latency in microseconds (the 99th percentile of clat_ns,
  the time from submit to completion)

The runner wraps the fio output with the parameters it used, so the parser
does not have to guess the block size or queue depth from file names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MIB = 1024 * 1024
DIRECTIONS = ("read", "write")


class FioResultError(ValueError):
    """Raised when a saved run cannot be turned into numbers."""


@dataclass(frozen=True)
class DirectionResult:
    target: str
    job: str
    direction: str
    block_size: str
    iodepth: int
    rwmix: int | None
    repeat: int
    bw_mib_s: float
    iops: float
    p99_latency_us: float | None
    fio_version: str


def _throughput_bytes_per_s(section: dict[str, Any]) -> float:
    if "bw_bytes" in section:
        return float(section["bw_bytes"])
    # Older fio (before 3.31) reports bw in KiB/s only.
    return float(section.get("bw", 0)) * 1024.0


def _p99_us(section: dict[str, Any]) -> float | None:
    clat = section.get("clat_ns") or {}
    percentiles = clat.get("percentile") or {}
    for key, value in percentiles.items():
        if abs(float(key) - 99.0) < 1e-9:
            return float(value) / 1000.0
    return None


def parse_run(wrapper: dict[str, Any]) -> list[DirectionResult]:
    """Turn one saved run into one row per direction that did I/O.

    ``wrapper`` looks like::

        {"target": "nas", "job": "rand-read", "block_size": "4k",
         "iodepth": 16, "rwmix": null, "repeat": 1, "fio": {...fio JSON...}}
    """
    try:
        fio = wrapper["fio"]
        jobs = fio["jobs"]
        fio_version = str(fio.get("fio version", "unknown"))
        target = str(wrapper["target"])
        job_name = str(wrapper["job"])
        block_size = str(wrapper["block_size"])
        iodepth = int(wrapper["iodepth"])
        rwmix = wrapper.get("rwmix")
        repeat = int(wrapper["repeat"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FioResultError(f"not a benchmark run file: {exc}") from exc

    if len(jobs) != 1:
        raise FioResultError(f"expected one fio job per run, found {len(jobs)}")
    job = jobs[0]
    if job.get("error", 0):
        raise FioResultError(
            f"fio reported error {job['error']} for {target}/{job_name}; "
            "a failed run is not compared with the others"
        )

    rows: list[DirectionResult] = []
    for direction in DIRECTIONS:
        section = job.get(direction) or {}
        if section.get("io_bytes", 0) <= 0 and section.get("total_ios", 0) <= 0:
            continue
        rows.append(
            DirectionResult(
                target=target,
                job=job_name,
                direction=direction,
                block_size=block_size,
                iodepth=iodepth,
                rwmix=None if rwmix is None else int(rwmix),
                repeat=repeat,
                bw_mib_s=_throughput_bytes_per_s(section) / MIB,
                iops=float(section.get("iops", 0.0)),
                p99_latency_us=_p99_us(section),
                fio_version=fio_version,
            )
        )
    if not rows:
        raise FioResultError(f"{target}/{job_name} repeat {repeat} moved no data")
    return rows
