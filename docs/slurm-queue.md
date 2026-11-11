# Slurm GPU queue notes

Slurm is the scheduler that runs batch jobs on a cluster. Here it runs my two GPU workstations so
that drawing-review runs and model benchmarks share the GPUs without fighting each other.

## Files

| Path | What it is |
|---|---|
| `slurm/etc/slurm.conf` | the cluster: nodes, partitions, GPU accounting, fair-share, preemption, backfill |
| `slurm/etc/gres.conf` | which device files are the GPUs on each workstation |
| `slurm/etc/setup-accounts.sh` | creates the account, the QOS and the per-user GPU limit in the accounting database |
| `slurm/jobs/review.sbatch` | a one-GPU drawing-review run in the `review` partition |
| `slurm/jobs/bench.sbatch` | a one-GPU model benchmark in the `bench` partition, requeueable |
| `slurm/scripts/submit_batch.sh` | submits a text file of mixed review and benchmark jobs |
| `slurm/sim/queue.py` | a simulator of the same rules, used by the tests |
| `slurm/sim/report.py` | prints occupancy, waiting time and fairness per user |
| `slurm/tests/` | tests of the rules and checks that the configs agree with each other |

## How the rules work

- **Partitions and tiers.** `review` has tier 2 and `bench` has tier 1. A job in a higher tier may
  requeue jobs in a lower tier (`PreemptType=preempt/partition_prio`, `PreemptMode=REQUEUE`).
  A requeued benchmark starts again from the beginning. Its partial run is lost, which the report
  counts as "GPU-minutes lost to requeue".
- **GPU accounting.** GPUs are a generic resource (`gres/gpu`). Jobs ask for them with `--gres=gpu:1`,
  and the accounting database records how many GPU-minutes each user used.
- **Fair-share.** Priority is tier first, then fair-share, then age. Recent GPU use lowers a user's
  fair-share, and the use fades with a seven-day half-life.
- **Quota.** `setup-accounts.sh` sets `MaxTRESPerUser=gres/gpu=2` on the `bench` QOS, so one user
  cannot hold more than two GPUs for benchmarks at once.
- **Backfill.** The scheduler may start a short job in a gap if it will finish before the waiting
  top job could start. A long job never jumps the queue.

## Using it

On the controller, once `slurmdbd` is running:

```sh
USERS="yourname" MAX_GPUS_PER_USER=2 slurm/etc/setup-accounts.sh
```

To submit a mixed batch, write one job per line in a text file:

```text
review /data/drawings/rev-01.pdf
bench llama-3.1-8b
```

Then run `slurm/scripts/submit_batch.sh batch.txt`. Use `--dry-run` first to see the `sbatch` commands.
Check the queue with `squeue`, and get the numbers for a finished batch with:

```sh
sacct -P -n -X -a -S 2026-01-01 -o User,Submit,Start,End,AllocTRES,State > sacct.txt
python -m slurm.sim.report --sacct sacct.txt
```

To see the rules without a cluster, run the simulator:

```sh
python -m slurm.sim.report --demo
python -m pytest -q slurm/tests
```

## Limits

- The simulator treats all GPUs as one pool. Real Slurm places a job on one node's GPUs, so a real
  queue can be fuller than the simulation shows.
- The configs are checked against the simulator by tests, but there is no Slurm daemon in CI. A
  real `slurmctld` has to be started on the controller to test `slurm.conf` for real.
- Wait times in the demo come from simulated minutes, not from measured jobs.
