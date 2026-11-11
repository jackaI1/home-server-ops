# DiskAlmostFull

**What it means:** a disk has less than 10% free for 10 minutes. Writes will start to fail soon. Databases and backups fail first.

**Do this now**
1. Find what is filling it: `sudo du -xh --max-depth=1 <mountpoint> | sort -h | tail -15`.
2. Free space by removing files you are sure about, such as old logs (`sudo journalctl --vacuum-size=500M`) or failed backup partial files.
3. If a backup is writing right now, stop it before deleting anything near it: `sudo systemctl stop <backup service>`.
4. Confirm the "Disks below 10% free" panel goes back to 0.
