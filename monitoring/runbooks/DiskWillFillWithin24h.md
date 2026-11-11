# DiskWillFillWithin24h

**What it means:** a disk has less than 25% free, and it has been losing space fast enough (over the last 6 hours) that it would be full within a day. The alert needs both conditions, so a disk that is simply full of old data does not fire it.

**Check first**
1. Open the "Disk used by mount" and "Time until each disk is full" panels for the mount named in the alert.
2. On the server, find the big folders: `sudo du -xh --max-depth=1 <mountpoint> | sort -h | tail -15`.
3. Look for a growing log, a stuck backup partial file (`*.partial`) or a container image cache.

**Fix**
- Remove files you know you can delete, such as old logs or `*.partial` backup files from a failed run.
- Move or archive old backups. The retention setting is in `k8s/charts/home-ops/values.yaml` (`backup.retentionDays`).
- If the growth is expected, extend the disk or change the alert's threshold in `monitoring/prometheus/rules/home-server.yml` and update the tests.
