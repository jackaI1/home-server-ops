#!/usr/bin/env bash
# Never pass token values as process arguments or write them into the repository.
set -euo pipefail
umask 077
state=$(mktemp -d)
trap 'rm -rf "$state"' EXIT
for name in client intake worker device; do
  if kubectl -n device-automation get secret "$name-auth" >/dev/null 2>&1; then
    echo "Keeping existing $name-auth"
  else
    python3 -c 'import secrets; print(secrets.token_urlsafe(32), end="")' > "$state/token"
    kubectl -n device-automation create secret generic "$name-auth" --from-file=token="$state/token"
  fi
done
