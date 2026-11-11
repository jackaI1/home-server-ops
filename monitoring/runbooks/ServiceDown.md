# ServiceDown

**What it means:** Prometheus could not scrape one of its own exporters (node, alertmanager, blackbox or prometheus) for 5 minutes. The job name is in the alert.

**Why it matters:** while an exporter is down, Prometheus has no fresh numbers for that part of the server, so other alerts can be silent when they should not be.

**Check first**
1. On the server, run `docker compose ps` in the monitoring folder and look for a service that is not "running".
2. Run `docker compose logs --tail=50 <service>` for that service.

**Fix**
- Restart the stack: `docker compose up -d --wait` in the monitoring folder. The compose file restarts stopped services automatically, so a crash that repeats needs the logs.
- If the whole server is unreachable, this alert is correct but the cause is outside the stack. Check power, network and SSH first.
