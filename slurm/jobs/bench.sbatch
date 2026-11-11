#!/usr/bin/env bash
# Model benchmark: one GPU, long, runs in the low-tier bench partition. It is requeued if a review needs the GPU.
#SBATCH --job-name=bench
#SBATCH --partition=bench
#SBATCH --account=homelab
#SBATCH --qos=bench
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=04:00:00
#SBATCH --requeue
#SBATCH --output=%x-%j.out
set -euo pipefail
srun python3 "${BENCH_SCRIPT:-benchmark.py}" --model "${MODEL:?set MODEL}"
