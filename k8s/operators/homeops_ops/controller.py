"""Run a controller loop: reconcile every few seconds until stopped.

  python -m homeops_ops.controller selfheal --manifest examples/services.yaml --interval 10
  python -m homeops_ops.controller gpuqueue --quota examples/quota.yaml --namespace gpu-jobs --interval 5
  add --once to run a single pass and exit (used by the tests and by the kind script)
"""

import argparse
import logging
import signal
import sys
import time

from homeops_ops import gpuqueue, selfheal
from homeops_ops.kube import Kube

log = logging.getLogger("homeops_ops")


class Stop(Exception):
    pass


def _raise_stop(*_):
    raise Stop()


def loop(step, interval, once=False, sleep=time.sleep):
    """Call step() until stopped. An error in one pass is logged and the loop carries on."""
    if once:
        return step()
    signal.signal(signal.SIGTERM, _raise_stop)
    try:
        while True:
            try:
                step()
            except Exception:  # keep the controller alive; the next pass retries
                log.exception("reconcile failed; retrying in %ss", interval)
            sleep(interval)
    except (Stop, KeyboardInterrupt):
        log.info("stopped")
        return None


def main(argv=None, kube=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="controller", required=True)
    heal = sub.add_parser("selfheal", help="keep declared services and certificates in place")
    heal.add_argument("--manifest", required=True)
    queue = sub.add_parser("gpuqueue", help="admit GPU jobs against team quotas")
    queue.add_argument("--quota", required=True)
    queue.add_argument("--namespace", default="gpu-jobs")
    for p in (heal, queue):
        p.add_argument("--interval", type=float, default=10.0)
        p.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    kube = kube or Kube()

    if args.controller == "selfheal":
        manifest = selfheal.load_manifest(args.manifest)

        def step():
            actions = selfheal.reconcile(kube, manifest)
            for action, kind, name in actions:
                log.info("selfheal: %s %s/%s", action, kind, name)
    else:
        quota = gpuqueue.load_quota(args.quota)

        def step():
            actions = gpuqueue.reconcile_once(kube, args.namespace, quota)
            for op, name, _ in actions:
                log.info("gpuqueue: %s %s", op, name)

    loop(step, args.interval, once=args.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())
