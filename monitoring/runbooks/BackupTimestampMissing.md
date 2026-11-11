# BackupTimestampMissing

**What it means:** Prometheus has not seen the backup timestamp for an hour. The timestamp file is written by the backup job into the textfile folder that node_exporter reads.

**Check first**
1. Look at the `BACKUP_TEXTFILE_DIR` value in `monitoring/.env`. It must be the host folder where `home-ops-backup.prom` is written.
2. On the server, check that the file exists and is recent: `ls -l <textfile folder>`.
3. Run the backup job manually (see [BackupStale](BackupStale.md)). A successful run rewrites the file.

**Fix**
- If the path is wrong, set `BACKUP_TEXTFILE_DIR` and run `docker compose up -d` again.
- If the job is failing, follow [BackupStale](BackupStale.md).
