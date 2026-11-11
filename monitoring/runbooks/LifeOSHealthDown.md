# LifeOSHealthDown

**What it means:** the page at https://lifeos.jacklai.ca/healthz has failed for 10 minutes. The site may still load while the health check fails, for example when the database is unreachable.

**Check first**
1. Open https://lifeos.jacklai.ca/healthz and note the status code.
2. Compare with the "LifeOS demo reachable" panel. If both fail, follow [LifeOSDemoDown](LifeOSDemoDown.md).
3. If only the health check fails, the app is running but a dependency is not.

**Fix**
- Restart the app with the restart runbook (see the command in [LifeOSDemoDown](LifeOSDemoDown.md)), then check the health path again.
- If the restart does not clear it, check the app's logs on the server before restarting again.
