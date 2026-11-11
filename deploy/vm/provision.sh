#!/usr/bin/env bash
# Set up an Ubuntu 24.04 VM to run the home server's Docker services.
#
# What it does, in order:
#   1. installs Docker, the Compose plugin, the firewall (ufw) and automatic security updates
#   2. opens only SSH, HTTP and HTTPS
#   3. copies the Compose files and the health checker into the install directory
#   4. creates the config files from their examples if they are missing (edit them afterwards)
#   5. installs a systemd timer that runs the health check every 15 minutes
#   6. starts the services and waits until Caddy reports healthy
#
# Run it from a clone of this repository, on the VM, as root:
#   sudo deploy/vm/provision.sh
# Use --dry-run to print the steps without changing anything.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
INSTALL_DIR="/opt/home-ops"
DRY_RUN=0
SKIP_SYSTEM=0

usage() {
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'USAGE'

Options:
  --install-dir DIR   where the services live (default /opt/home-ops)
  --skip-system       skip packages, firewall and systemd (used by CI to test the copy and start steps)
  --dry-run           print the steps and do nothing
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --install-dir) INSTALL_DIR="${2:?--install-dir needs a path}"; shift 2 ;;
    --skip-system) SKIP_SYSTEM=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

die() { echo "error: $*" >&2; exit 1; }

# run <command...>: prints the command, and runs it unless this is a dry run.
run() {
  echo "+ $*"
  if [ "$DRY_RUN" -eq 0 ]; then
    "$@"
  fi
}

if [ "$DRY_RUN" -eq 0 ] && [ "$SKIP_SYSTEM" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
  die "run as root (sudo), or pass --skip-system or --dry-run"
fi

if [ "$SKIP_SYSTEM" -eq 0 ]; then
  echo "== 1. packages"
  run apt-get update
  run env DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 ufw unattended-upgrades

  echo "== 2. firewall: only SSH, HTTP and HTTPS"
  run ufw allow OpenSSH
  run ufw allow 80/tcp
  run ufw allow 443/tcp
  run ufw --force enable
fi

echo "== 3. copy the services into $INSTALL_DIR"
run install -d -m 0750 "$INSTALL_DIR/compose" "$INSTALL_DIR/health"
run cp -r "$REPO/deploy/compose/." "$INSTALL_DIR/compose/"
run install -m 0644 "$REPO/deploy/health/check_health.py" "$INSTALL_DIR/health/check_health.py"

echo "== 4. config files (created only when missing)"
if [ ! -f "$INSTALL_DIR/compose/.env" ]; then
  run install -m 0600 "$INSTALL_DIR/compose/.env.example" "$INSTALL_DIR/compose/.env"
  echo "   edit $INSTALL_DIR/compose/.env and set DOMAIN and ACME_EMAIL"
fi
if [ "$SKIP_SYSTEM" -eq 0 ]; then
  run install -d -m 0750 /etc/home-ops
  if [ ! -f /etc/home-ops/health.env ]; then
    run install -m 0600 "$REPO/deploy/vm/health.env.example" /etc/home-ops/health.env
    echo "   edit /etc/home-ops/health.env and set HEALTH_URLS, HEALTH_TLS and ALERT_WEBHOOK"
  fi

  echo "== 5. health check timer"
  for unit in home-ops-health.service home-ops-health.timer; do
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "+ install $unit to /etc/systemd/system (install dir substituted)"
    else
      sed "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$REPO/deploy/vm/systemd/$unit" > "/etc/systemd/system/$unit"
    fi
  done
  run systemctl daemon-reload
  run systemctl enable --now home-ops-health.timer
fi

echo "== 6. start the services and wait for Caddy to report healthy"
if [ "$DRY_RUN" -eq 0 ] && grep -q 'example\.com' "$INSTALL_DIR/compose/.env"; then
  # Starting now would ask Let's Encrypt for a placeholder domain. Start it after editing .env.
  echo "   .env still has placeholder values, so the services are not started yet."
  echo "   after editing it, run: docker compose --project-directory $INSTALL_DIR/compose up -d --wait"
else
  run docker compose --project-directory "$INSTALL_DIR/compose" up -d --wait
fi

echo "done. Check with: systemctl list-timers home-ops-health.timer && docker compose --project-directory $INSTALL_DIR/compose ps"
