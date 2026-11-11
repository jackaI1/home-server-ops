#!/usr/bin/env bash
# Submit a mixed batch: review runs (high tier) and benchmark runs (low tier) for the home GPU queue.
#
# Input is a plain text file, one job per line:
#   review <input-path>
#   bench  <model-name>
# Lines starting with # are ignored.
#
#   slurm/scripts/submit_batch.sh batch.txt            submit with sbatch
#   slurm/scripts/submit_batch.sh --dry-run batch.txt  print the sbatch commands only
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JOBS="$HERE/../jobs"
DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then DRY_RUN=1; shift; fi
[ $# -eq 1 ] || { echo "usage: $0 [--dry-run] batch.txt" >&2; exit 2; }
[ -f "$1" ] || { echo "no such batch file: $1" >&2; exit 2; }

while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  read -r kind arg <<<"$line"
  case "$kind" in
    review)
      cmd=(sbatch "--export=ALL,INPUT=$arg" "$JOBS/review.sbatch") ;;
    bench)
      cmd=(sbatch "--export=ALL,MODEL=$arg" "$JOBS/bench.sbatch") ;;
    *)
      echo "unknown job kind in batch file: $kind" >&2; exit 2 ;;
  esac
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '%q ' "${cmd[@]}"; echo
  else
    "${cmd[@]}"
  fi
done < "$1"
