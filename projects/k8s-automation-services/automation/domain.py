import re

DEVICES = {"lab-switch", "lab-switch-faulty"}
TASKS = {"inventory", "link-check"}


class Problem(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def validate_job(payload):
    if not isinstance(payload, dict) or set(payload) != {"device", "task"}:
        raise Problem(422, "Provide only device and task")
    if (
        not isinstance(payload["device"], str)
        or payload["device"] not in DEVICES
        or not isinstance(payload["task"], str)
        or payload["task"] not in TASKS
    ):
        raise Problem(422, "Unknown device or task")
    return payload


def validate_key(key):
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", key):
        raise Problem(422, "Provide an Idempotency-Key of 1-100 letters, digits, dots or hyphens")
    return key
