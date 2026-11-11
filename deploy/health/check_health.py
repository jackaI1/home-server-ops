"""Health check for the home server: services answer, and certificates have time left.

It checks two things:
  * each URL answers with a status below 400 (a service that is down or returns an error fails)
  * each host:port presents a certificate that verifies and has more than --warn-days left

Any failure prints a line, optionally posts a JSON alert to ALERT_WEBHOOK, and exits 1.
Only the Python standard library is used, so the systemd timer needs nothing extra installed.

Settings can come from the command line or from environment variables (the systemd timer uses the
environment): HEALTH_URLS, HEALTH_TLS, HEALTH_WARN_DAYS, ALERT_WEBHOOK.
"""

import argparse
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_WARN_DAYS = 14
DEFAULT_TIMEOUT = 10.0


@dataclass
class Result:
    name: str
    ok: bool
    detail: str


def check_url(url, timeout=DEFAULT_TIMEOUT, cafile=None):
    """GET the URL. Redirects are followed. Status 400 and above is a failure."""
    context = ssl.create_default_context(cafile=cafile) if url.startswith("https://") else None
    request = urllib.request.Request(url, headers={"User-Agent": "home-ops-health/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as resp:
            status = resp.status
    except urllib.error.HTTPError as err:
        return Result(url, False, f"HTTP {err.code}")
    except (urllib.error.URLError, OSError, ValueError) as err:
        reason = getattr(err, "reason", err)
        return Result(url, False, f"request failed: {reason}")
    return Result(url, status < 400, f"HTTP {status}")


def cert_days_left(host, port=443, cafile=None, timeout=DEFAULT_TIMEOUT, now=None):
    """Connect with full verification and return the days until the certificate expires."""
    context = ssl.create_default_context(cafile=cafile)
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert()
    not_after = ssl.cert_time_to_seconds(cert["notAfter"])
    now = time.time() if now is None else now
    return (not_after - now) / 86400


def check_cert(target, warn_days=DEFAULT_WARN_DAYS, cafile=None, timeout=DEFAULT_TIMEOUT, now=None):
    host, _, port = target.partition(":")
    port = int(port or 443)
    name = f"tls {host}:{port}"
    try:
        days = cert_days_left(host, port, cafile=cafile, timeout=timeout, now=now)
    except ssl.SSLCertVerificationError as err:
        return Result(name, False, f"certificate does not verify: {err.verify_message}")
    except (OSError, ssl.SSLError) as err:
        return Result(name, False, f"TLS connection failed: {err}")
    if days < warn_days:
        return Result(name, False, f"certificate expires in {days:.1f} days (warn below {warn_days})")
    return Result(name, True, f"certificate valid for {days:.0f} more days")


def send_alert(webhook, failures, now=None):
    """POST a JSON summary. Returns True when the webhook accepted it."""
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(time.time() if now is None else now))
    lines = [f"{r.name}: {r.detail}" for r in failures]
    body = json.dumps({"title": f"Home server check failed ({stamp})", "message": "\n".join(lines)}).encode()
    request = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT):
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def split(value):
    return [item for item in (value or "").replace(",", " ").split() if item]


def run_checks(urls, tls_targets, warn_days, cafile=None, timeout=DEFAULT_TIMEOUT):
    results = [check_url(u, timeout=timeout, cafile=cafile) for u in urls]
    results += [check_cert(t, warn_days=warn_days, cafile=cafile, timeout=timeout) for t in tls_targets]
    return results


def main(argv=None, env=None, out=sys.stdout):
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", action="append", default=None, help="URL to request (repeatable)")
    parser.add_argument("--tls", action="append", default=None, help="host:port whose certificate to check")
    parser.add_argument("--warn-days", type=int, default=None)
    parser.add_argument("--cafile", default=None, help="CA bundle to verify against (for a local CA)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)

    urls = args.url if args.url is not None else split(env.get("HEALTH_URLS"))
    tls_targets = args.tls if args.tls is not None else split(env.get("HEALTH_TLS"))
    warn_days = args.warn_days if args.warn_days is not None else int(env.get("HEALTH_WARN_DAYS", DEFAULT_WARN_DAYS))
    if not urls and not tls_targets:
        parser.error("nothing to check: pass --url or --tls, or set HEALTH_URLS or HEALTH_TLS")

    results = run_checks(urls, tls_targets, warn_days, cafile=args.cafile, timeout=args.timeout)
    failures = [r for r in results if not r.ok]
    for r in results:
        print(("OK    " if r.ok else "FAIL  ") + f"{r.name}: {r.detail}", file=out)

    webhook = env.get("ALERT_WEBHOOK", "").strip()
    if failures and webhook:
        if not send_alert(webhook, failures):
            print("could not send the alert to ALERT_WEBHOOK", file=out)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
