# Storage benchmarks

This is the detail behind the storage section of the README. It covers the
commands, what each number means, how the runs are kept fair, and what the
tests check.

## Why the numbers are repeated

A single fio run can be fast or slow for reasons that have nothing to do with
the disk: another backup was running, the NAS was busy with a scrub, or the
kernel had the file cached. So every configuration runs five times by default,
and the tables and plots show the spread between the fastest and slowest run.
A change only means something when it is bigger than that spread.

The runs go round-robin: every configuration runs once, then the whole set runs
again. A slow hour on the NAS then affects every configuration a little, instead
of making the last configuration look slower than the first.

## The three numbers

- **Throughput (MiB/s)**: how much data moved per second.
- **IOPS**: how many read or write operations completed per second. Small random
  reads are judged by this number, not by throughput.
- **p99 latency (microseconds)**: 99 out of 100 operations finished within this
  time. It shows the slow tail, which is what makes a backup feel stuck.

Latency is measured from when fio submits an operation to when it completes.

## The fixed job files

Each file in `benchmarks/jobs/` describes one workload. The runner only changes
the block size, queue depth, read percentage, file size and time, through
environment variables, so every run of a job has the same shape.

| Job file | What it does |
| --- | --- |
| `seq-read.fio` | reads one large file from start to end |
| `seq-write.fio` | writes one large file, then flushes it to disk |
| `rand-read.fio` | reads blocks from random places in the file |
| `rand-write.fio` | writes blocks to random places, then flushes |
| `rand-mixed.fio` | a random mix; the read percentage comes from `--rwmix` |

Each job uses direct I/O by default, which skips the Linux page cache. Without
that, the second run would partly measure RAM. Use `--buffered` only when you
want to measure the cache on purpose.

## Commands

Install fio on the machine that holds the disks, then run the benchmark from the
repository folder. For example, to test the NAS mount and the local SSD:

```sh
sudo apt install fio
python -m pip install -r benchmarks/requirements.txt
python -m benchmarks run \
  --target nas=/mnt/nas/bench \
  --target local=/srv/bench \
  --out ~/bench-results/2026-11-14
```

The test file is `homeops-fio-benchmark.dat` in each target folder. It is
deleted when the runs for that target finish or fail. Make sure each folder has
room for the file (1 GB by default, set with `--size`).

The default grid is 5 jobs, 2 block sizes (4k and 1m), 2 queue depths (1 and 16)
and 5 repeats. That is 20 configurations and 100 runs per target. Each run is
30 seconds plus 2 seconds of warm-up, so a full target takes about an hour of
measuring, plus the time to create the test file. For a quick check, shorten it:

```sh
python -m benchmarks run --target nas=/mnt/nas/bench --out ~/bench-quick \
  --size 256M --runtime 5 --repeats 3 --jobs rand-read,rand-write --block-sizes 4k
```

Other commands:

```sh
python -m benchmarks report ~/bench-results/2026-11-14      # rebuild CSVs and plots from saved runs
python -m benchmarks compare ~/bench-results/old ~/bench-results/2026-11-14
```

`compare` lists the configurations that dropped more than 10% in throughput or
rose more than 20% in p99 latency. Its exit code is 0 when nothing is flagged, 1
when something is, and 2 when the two runs cannot be compared. Use
`--bw-drop` and `--p99-rise` to change the limits.

## What a result folder contains

```text
environment.json                  kernel, fio version, filesystem and mount options per target, settings
raw/<target>/<config>/run01.json  one saved fio result per run, with the settings it used
runs.csv                          one row per run and direction
summary.csv                       one row per configuration: median, min, max and spread
plots/bw_mib_s.png                throughput, one dot per run
plots/iops.png                    IOPS, one dot per run
plots/p99_latency_us.png          p99 latency, one dot per run
```

The raw files are the source of truth. `report` can always rebuild the tables
and plots from them. `run` also skips any run whose raw file already exists, so
an interrupted run can be started again with the same command.

## Keeping comparisons fair

Before two results are compared, `compare` checks:

- the kernel version and the fio version,
- the test file size, runtime, I/O engine and direct-I/O setting,
- the filesystem type and mount options of each target.

If anything differs, it stops and says what differs. A new kernel or a
remounted NAS can change the numbers by themselves, and the comparison should
not blame the disk for that. `--allow-mismatch` shows the numbers anyway, with a
warning at the top.

The `environment.json` file stores these values, so a result folder can be read
later without remembering what the machine looked like.

## What the tests check

`python -m pytest -q benchmarks/tests` runs on any machine with Python 3.11:

- **Parsing**: the saved fio JSON in `benchmarks/samples/` is turned into the
  right throughput, IOPS and p99 values. Older fio output (KiB/s only) is read
  correctly, a missing percentile is kept as "no value" rather than zero, and a
  failed fio job is refused instead of being averaged in.
- **Summaries**: the median, min, max and spread are computed from known values.
- **Plots**: the three PNG files are written from the saved runs, and a fifth
  target is refused because the palette has four colours.
- **Compare**: a changed kernel or filesystem is refused, and a slower run is
  flagged.
- **Command line**: the grid and the round-robin order are correct. When fio is
  installed, a short real run is done against a temporary folder and its test
  file is checked to be gone.

GitHub Actions (`.github/workflows/storage-benchmarks.yml`) runs the tests on
Ubuntu, then does a short real run with direct I/O and libaio, checks that the
test file was removed, and compares the run with itself, which must show no
flags.

## Limits

- The runner measures one machine at a time. A NAS seen through a network mount
  is measured with that network in the path, so the result is the NAS and the
  link together.
- Direct I/O skips the cache on this machine, but a NAS or a disk controller can
  still cache. Use a `--size` several times bigger than those caches when you
  want the disk alone.
- The CI run uses a virtual machine disk, so it proves the code works, not how
  fast any disk is.
- Five repeats show the spread, but they are not a long-term record. For a slow
  trend over months, keep one result folder per month and run `compare` on each
  pair of neighbouring months.
