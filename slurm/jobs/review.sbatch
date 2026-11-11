#!/usr/bin/env bash
# Drawing-review run: one GPU, short, runs in the high-tier review partition.
#SBATCH --job-name=review
#SBATCH --partition=review
#SBATCH --account=homelab
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=%x-%j.out
set -euo pipefail
srun python3 "${REVIEW_SCRIPT:-review_drawing.py}" --input "${INPUT:?set INPUT}"
