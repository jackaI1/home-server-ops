import time

from automation.domain import Problem
from automation.http import call


def execute(job, device_url, device_token):
    """Named read-only scripts; never a shell, user URL or arbitrary command."""
    base = f"{device_url}/devices/{job['device']}"
    version = call(f"{base}/version", device_token)
    result = {
        "hostname": version["hostname"],
        "model": version["model"],
        "firmware": version["firmware"],
    }
    if job["task"] == "inventory":
        return "succeeded", result
    interfaces = call(f"{base}/interfaces", device_token)["interfaces"]
    down = [interface["name"] for interface in interfaces if interface["state"] != "up"]
    return ("failed" if down else "succeeded"), {**result, "interfaces": interfaces, "down": down}


def run(settings, stop, heartbeat):
    while not stop.is_set():
        try:
            job = call(f"{settings['AUDIT_URL']}/internal/claim", settings["WORKER_TOKEN"], {})
            heartbeat[0] = time.monotonic()
            if job:
                try:
                    status, result = execute(job, settings["DEVICE_URL"], settings["DEVICE_TOKEN"])
                except (Problem, KeyError, TypeError):
                    status, result = "failed", {"error": "Device check unavailable"}
                call(
                    f"{settings['AUDIT_URL']}/internal/finish",
                    settings["WORKER_TOKEN"],
                    {"id": job["id"], "lease": job["lease"], "status": status, "result": result},
                )
        except Problem:
            # No successful completion means the audit lease recovers this job after a crash/outage.
            pass
        stop.wait(float(settings.get("POLL_SECONDS", "0.5")))
