#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
exec ./scripts/lab.sh smoke --case session-flap --output artifacts/session-flap
