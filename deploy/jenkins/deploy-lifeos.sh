#!/usr/bin/env bash
# Deploy one LifeOS image on this host. Used by the lifeos-deploy job.
#
#   deploy-lifeos.sh IMAGE ENV_FILE DEPLOY_DIR
#
# It copies the compose file and the secret env file into DEPLOY_DIR, starts the stack and waits for the
# health check. If the new image does not become healthy, it starts the previous image again and exits 1.
# DOCKER overrides the docker binary, which the tests use to run without a daemon.
set -euo pipefail

IMAGE="${1:?usage: deploy-lifeos.sh IMAGE ENV_FILE DEPLOY_DIR}"
ENV_FILE="${2:?usage: deploy-lifeos.sh IMAGE ENV_FILE DEPLOY_DIR}"
DEPLOY_DIR="${3:?usage: deploy-lifeos.sh IMAGE ENV_FILE DEPLOY_DIR}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER="${DOCKER:-docker}"

up() { # up IMAGE -> start the stack with that image and wait until it is healthy
  LIFEOS_IMAGE="$1" "$DOCKER" compose -p lifeos -f "$DEPLOY_DIR/compose.yml" up -d --wait --remove-orphans
}

mkdir -p "$DEPLOY_DIR"
chmod 700 "$DEPLOY_DIR"
install -m 600 "$ENV_FILE" "$DEPLOY_DIR/lifeos.env"
install -m 644 "$HERE/lifeos-compose.yml" "$DEPLOY_DIR/compose.yml"
"$DOCKER" image inspect "$IMAGE" >/dev/null

PREVIOUS=""
if [[ -f "$DEPLOY_DIR/current-image" ]]; then
  PREVIOUS="$(cat "$DEPLOY_DIR/current-image")"
fi

if up "$IMAGE"; then
  echo "$IMAGE" > "$DEPLOY_DIR/current-image"
  echo "deployed $IMAGE"
  exit 0
fi

echo "deploy of $IMAGE did not become healthy" >&2
if [[ -n "$PREVIOUS" ]]; then
  echo "rolling back to $PREVIOUS" >&2
  up "$PREVIOUS" || echo "rollback to $PREVIOUS also failed; check the logs" >&2
fi
exit 1
