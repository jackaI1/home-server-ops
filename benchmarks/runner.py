"""Run fio over a grid of settings, several times each, and save every result.

Each run is one fio invocation with one fixed job file from ``benchmarks/jobs``.
The runs are ordered round-robin: every configuration runs once, then the whole
set runs again. A slow hour on the NAS then hits every configuration a little,
instead of making one configuration look slower than the others.

Everything fio writes goes under the output folder::

    out/environment.json                 kernel, filesystem, fio version, settings
    out/raw/<target>/<config>/run01.json  one wrapped fio result per run

fio writes one test file per target. It is kept between runs, so fio does not
rewrite it for every run, and it is deleted in a ``finally`` block at the end
of the target, so an interrupted run does not leave a large file on the disk
being measured.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

HERE = Path(__file__).resolve().parent
JOB_DIR = HERE / "jobs"
TEST_FILE_NAME = "homeops-fio-benchmark.dat"

JOBS = ("seq-read", "seq-write", "rand-read", "rand-write", "rand-mixed")
MIXED_JOBS = frozenset({"rand-mixed"})
DEFAULT_BLOCK_SIZES = ("4k", "1m")
DEFAULT_IODEPTHS = (1, 16)
DEFAULT_RWMIX = (70,)


class RunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    name: str
    directory: Path


@dataclass(frozen=True)
class RunSpec:
    target: Target
    job: str
    block_size: str
    iodepth: int
    rwmix: int | None

    @property
    def config(self) -> str:
        name = f"{self.job}-bs{self.block_size}-qd{self.iodepth}"
        if self.rwmix is not None:
            name += f"-mix{self.rwmix}"
        return name


@dataclass
class Settings:
    size: str = "1G"
    runtime: int = 30
    ramp: int = 2
    ioengine: str = "libaio"
    direct: bool = True
    repeats: int = 5
    jobs: Sequence[str] = JOBS
    block_sizes: Sequence[str] = DEFAULT_BLOCK_SIZES
    iodepths: Sequence[int] = DEFAULT_IODEPTHS
    rwmix: Sequence[int] = DEFAULT_RWMIX


def parse_target(text: str) -> Target:
    """Parse ``name=/path`` from the command line into a Target."""
    if "=" not in text:
        raise RunnerError(f"target must look like name=/path, got {text!r}")
    name, _, path = text.partition("=")
    if not name or not all(c.isalnum() or c in "-_" for c in name):
        raise RunnerError(f"target name {name!r} may only use letters, digits, - and _")
    directory = Path(path).expanduser()
    if not directory.is_dir():
        raise RunnerError(f"target directory does not exist: {directory}")
    return Target(name=name, directory=directory)


def expand_specs(targets: Sequence[Target], settings: Settings) -> list[RunSpec]:
    """Return every configuration in the grid, in a stable order."""
    unknown = [job for job in settings.jobs if job not in JOBS]
    if unknown:
        raise RunnerError(f"unknown job(s): {', '.join(unknown)}; choose from {', '.join(JOBS)}")
    specs: list[RunSpec] = []
    for target in targets:
        for job in settings.jobs:
            mixes = settings.rwmix if job in MIXED_JOBS else (None,)
            for block_size in settings.block_sizes:
                for iodepth in settings.iodepths:
                    for mix in mixes:
                        specs.append(RunSpec(target, job, block_size, iodepth, mix))
    return specs


def iter_runs(specs: Sequence[RunSpec], repeats: int) -> Iterator[tuple[int, RunSpec]]:
    """Yield (repeat number, spec) round-robin: all configs once, then again."""
    for repeat in range(1, repeats + 1):
        for spec in specs:
            yield repeat, spec


def find_fio() -> str:
    path = shutil.which("fio")
    if path is None:
        raise RunnerError("fio is not installed; on Ubuntu run: sudo apt install fio")
    return path


def fio_version(fio: str) -> str:
    out = subprocess.run([fio, "--version"], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def filesystem_for(path: Path) -> dict[str, str]:
    """Report the filesystem type and mount options that hold ``path``.

    Uses findmnt on Linux. On other systems this returns "unknown", which the
    comparison code treats as a mismatch rather than as a match.
    """
    if shutil.which("findmnt") is None:
        return {"fstype": "unknown", "mount_options": "unknown"}
    out = subprocess.run(
        ["findmnt", "-T", str(path), "-n", "-o", "FSTYPE,OPTIONS"],
        capture_output=True,
        text=True,
    )
    parts = out.stdout.split()
    if out.returncode != 0 or len(parts) < 2:
        return {"fstype": "unknown", "mount_options": "unknown"}
    return {"fstype": parts[0], "mount_options": parts[1]}


def capture_environment(fio: str, targets: Sequence[Target], settings: Settings) -> dict:
    return {
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "system": platform.system(),
        "kernel": platform.release(),
        "fio_version": fio_version(fio),
        "python": sys.version.split()[0],
        "settings": {
            "size": settings.size,
            "runtime_s": settings.runtime,
            "ramp_s": settings.ramp,
            "ioengine": settings.ioengine,
            "direct": settings.direct,
            "repeats": settings.repeats,
        },
        "targets": {
            t.name: {"path": str(t.directory), **filesystem_for(t.directory)} for t in targets
        },
    }


def _fio_env(spec: RunSpec, settings: Settings) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "IOENGINE": settings.ioengine,
            "DIRECT": "1" if settings.direct else "0",
            "BS": spec.block_size,
            "IODEPTH": str(spec.iodepth),
            "SIZE": settings.size,
            "FILENAME": str(spec.target.directory / TEST_FILE_NAME),
            "RUNTIME": str(settings.runtime),
            "RAMP": str(settings.ramp),
            "RWMIX": str(spec.rwmix if spec.rwmix is not None else 0),
        }
    )
    return env


def run_one(fio: str, spec: RunSpec, repeat: int, settings: Settings, out_path: Path) -> dict:
    """Run fio once and save the wrapped result. Returns the wrapper."""
    job_file = JOB_DIR / f"{spec.job}.fio"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fio_json = out_path.with_suffix(".fio.tmp")
    cmd = [fio, "--output-format=json", f"--output={fio_json}", str(job_file)]
    timeout = settings.runtime * 4 + 600
    try:
        proc = subprocess.run(
            cmd,
            env=_fio_env(spec, settings),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            raise RunnerError(f"fio failed for {spec.target.name}/{spec.config}: {' | '.join(tail)}")
        fio_data = json.loads(fio_json.read_text())
    finally:
        fio_json.unlink(missing_ok=True)

    wrapper = {
        "target": spec.target.name,
        "job": spec.job,
        "block_size": spec.block_size,
        "iodepth": spec.iodepth,
        "rwmix": spec.rwmix,
        "repeat": repeat,
        "fio": fio_data,
    }
    out_path.write_text(json.dumps(wrapper, indent=2) + "\n")
    return wrapper


def remove_test_file(directory: Path) -> None:
    (directory / TEST_FILE_NAME).unlink(missing_ok=True)


def run_all(targets: Sequence[Target], settings: Settings, out_dir: Path, log=print) -> int:
    """Run the whole grid and return the number of runs saved."""
    fio = find_fio()
    specs = expand_specs(targets, settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    env = capture_environment(fio, targets, settings)
    (out_dir / "environment.json").write_text(json.dumps(env, indent=2) + "\n")

    total = len(specs) * settings.repeats
    log(f"{len(specs)} configurations x {settings.repeats} repeats = {total} fio runs")
    saved = 0
    try:
        for index, (repeat, spec) in enumerate(iter_runs(specs, settings.repeats), start=1):
            path = out_dir / "raw" / spec.target.name / spec.config / f"run{repeat:02d}.json"
            if path.exists():
                # Resume: a finished run from an earlier attempt is kept as is.
                saved += 1
                continue
            log(f"[{index}/{total}] {spec.target.name} {spec.config} run {repeat}")
            run_one(fio, spec, repeat, settings, path)
            saved += 1
    finally:
        for target in targets:
            remove_test_file(target.directory)
    return saved
