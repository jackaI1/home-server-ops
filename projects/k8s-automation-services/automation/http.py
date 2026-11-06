import json
import urllib.error
import urllib.request

from automation.domain import Problem


def read_json(response):
    data = response.read(65537)
    if len(data) > 65536:
        raise ValueError("Dependency response exceeds 64 KiB")
    return json.loads(data)


def call(url, token=None, payload=None, key=None, timeout=2):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if key:
        headers["Idempotency-Key"] = key
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = read_json(response)
            if result is not None and not isinstance(result, dict):
                raise Problem(503, "Dependency returned an invalid response")
            return result
    except urllib.error.HTTPError as error:
        # Preserve validation errors without exposing upstream internals.
        if error.code in (400, 404, 409, 422, 429):
            try:
                with error:
                    result = read_json(error)
                message = result.get("error") if isinstance(result, dict) else None
            except (OSError, ValueError):
                message = None
            if not isinstance(message, str):
                raise Problem(503, "Dependency returned an invalid response") from None
            raise Problem(error.code, message) from None
        raise Problem(503, "Dependency unavailable") from None
    except (OSError, ValueError):
        raise Problem(503, "Dependency unavailable") from None
