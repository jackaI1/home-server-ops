# VM deployment notes

This covers the Linux VM that runs my services in Docker, the HTTPS proxy in front of them, the
health check timer, and how to restore all of it onto a new VM.

## Layout

| Path | What it is |
|---|---|
| `deploy/vm/provision.sh` | sets up an Ubuntu 24.04 VM: packages, firewall, copies, timer, start |
| `deploy/compose/compose.yml` | the services: Caddy (HTTPS proxy) and the sample app |
| `deploy/compose/Caddyfile` | routes the domain to the app and sets security headers |
| `deploy/compose/.env.example` | `DOMAIN` and `ACME_EMAIL`, copied to `.env` on the VM |
| `deploy/health/check_health.py` | checks URLs and certificate expiry, alerts on failure |
| `deploy/vm/systemd/` | a service and a timer that run the health check every 15 minutes |
| `deploy/vm/health.env.example` | URLs, certificates, warning days and webhook for the check |
| `deploy/tests/` | tests for the config files and the health check |

## Setting up a VM

1. Install Ubuntu 24.04 Server on the VM, with SSH access for your user.
2. Point the domain's DNS `A` record at the VM's public address, and forward ports 80 and 443 to it.
3. Clone this repository on the VM and run the provisioning script as root:

   ```sh
   git clone https://github.com/jackaI1/home-server-ops.git
   cd home-server-ops
   sudo deploy/vm/provision.sh
   ```

   The script installs Docker and the Compose plugin, opens only SSH, 80 and 443 in `ufw`, enables
   automatic security updates, copies the services to `/opt/home-ops`, creates the two config files
   from their examples, and installs the health check timer.
4. Edit `/opt/home-ops/compose/.env`: set `DOMAIN` to the public name and `ACME_EMAIL` to an address
   that receives Let's Encrypt notices.
5. Edit `/etc/home-ops/health.env`: set `HEALTH_URLS`, `HEALTH_TLS` and `ALERT_WEBHOOK`.
6. Start the stack:

   ```sh
   docker compose --project-directory /opt/home-ops/compose up -d --wait
   ```

`provision.sh` does not start the stack while `.env` still has the `example.com` placeholders. This
stops it from asking Let's Encrypt for a domain that is not yours.

Use `deploy/vm/provision.sh --dry-run` to see every step without changing anything.

## Certificates and renewal

Caddy gets a certificate from Let's Encrypt the first time a name is requested, stores it in the
`caddy_data` volume, and renews it on its own about 30 days before it expires. There is no cron job
for renewal. The health check is the second check: it connects over TLS, verifies the chain, and
alerts when fewer than `HEALTH_WARN_DAYS` (14 by default) remain. If renewal ever fails, the alert
arrives weeks before the certificate expires.

For `DOMAIN=localhost`, Caddy issues a certificate from its own local certificate authority. That is
what the CI job uses. The root certificate is inside the container at
`/data/caddy/pki/authorities/local/root.crt`, and the health check can verify against it with
`--cafile`.

## Health check

`check_health.py` reads `HEALTH_URLS`, `HEALTH_TLS` and `HEALTH_WARN_DAYS` from the environment, or
the same values as command line options. It prints one line per check:

```text
OK    https://home.example.com/: HTTP 200
FAIL  tls home.example.com:443: certificate expires in 9.2 days (warn below 14)
```

The exit code is 1 when any check fails. When `ALERT_WEBHOOK` is set, a failure also sends a JSON
POST with a title and the failing lines. A webhook such as ntfy or a chat incoming webhook works.
If the webhook itself cannot be reached, the check still exits 1 and says so.

Run it by hand:

```sh
python3 /opt/home-ops/health/check_health.py --url https://home.example.com/ --tls home.example.com:443
systemctl list-timers home-ops-health.timer
journalctl -u home-ops-health.service -n 50
```

## Restoring onto a new VM

The services are rebuilt from Git and the two config files. Only the secrets and the certificate
store are not in Git, and the certificate store can be rebuilt.

1. Provision the new VM with the steps above, including `sudo deploy/vm/provision.sh`.
2. Copy `/opt/home-ops/compose/.env` and `/etc/home-ops/health.env` from your password manager, or
   write them again from the examples. Their contents are only a domain, an email address and a
   webhook URL.
3. Point the DNS record at the new VM's address and wait for it to resolve.
4. Start the stack: `docker compose --project-directory /opt/home-ops/compose up -d --wait`.
5. Run the health check by hand and read the output.

If you also saved the `caddy_data` volume (for example with `docker run --rm -v caddy_data:/data
-v "$PWD":/backup alpine tar czf /backup/caddy-data.tgz -C /data .`), you can restore it into the
new volume before starting, so Caddy keeps the same certificates and does not ask Let's Encrypt
again. Let's Encrypt limits how many certificates a domain can get in a week, so do not delete the
volume and start over repeatedly.

## Continuous integration

`.github/workflows/vm-deploy.yml` runs three jobs:

- **config**: runs `deploy/tests`, `docker compose config` on the Compose file, shellcheck on
  `provision.sh`, and a dry run of the provisioning script.
- **stack**: provisions into a temporary directory on the Ubuntu runner, starts the real stack with
  Caddy and the sample app, checks `https://localhost/` and the certificate with the health check,
  confirms that a dead URL makes the check fail, then restarts the stack and checks again.

The VM itself, its firewall and its DNS are not tested by CI. Those are checked by running the
provisioning script on the real VM.
