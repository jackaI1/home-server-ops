#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
exec ./scripts/lab.sh smoke --case mtu-mismatch --output artifacts/mtu-mismatch
