#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
exec ./scripts/lab.sh smoke --case bgp-prefix-filter --output artifacts/bgp-prefix-filter
