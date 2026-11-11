# BackupStale

**What it means:** the newest good backup of the database is more than 26 hours old. The backup job runs at 02:17 every night, so this means a night was missed or the job failed the integrity check.

**Check first**
1. Look at the backup job in Kubernetes: `kubectl -n home-ops get cronjob backup` and `kubectl -n home-ops get jobs`.
2. Read the last failed job's log: `kubectl -n home-ops logs job/<job name>`.
3. Look at the backups folder: `ls -lt <backup folder> | head`. A `*.partial` file means the dump did not finish.

**Fix**
- If the job failed, fix the cause (the log says why) and start a run now: `kubectl -n home-ops create job --from=cronjob/backup backup-manual-$(date +%s)`.
- Once the job finishes, check that the "Hours since last good backup" panel drops below 1.
- Copy the new backup off the server as well.

**Restore test:** if you are unsure a backup works, run the restore runbook against a copy in a test database, not the live one. See `ansible/runbooks/restore-backup.yml` and run it from the `ansible` folder.
