#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python_bin=${PYTHON:-.venv/bin/python}
if [[ ! -x "$python_bin" ]]; then python_bin=python3; fi
exec "$python_bin" -m routing_lab.cli "$@"
