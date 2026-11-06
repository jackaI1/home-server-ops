#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
exec ./scripts/lab.sh smoke --case wrong-ospf-area --output artifacts/wrong-ospf-area
