import argparse
import json
from pathlib import Path

from . import runtime
from .cases import CASES
from .diagnosis import diagnose, markdown_report


def smoke(output, cases):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # Refuse a pre-existing manual lab before entering our cleanup scope.
    runtime.ensure_stopped()
    try:
        runtime.up()
        (output / "ownership.json").write_text(json.dumps(runtime.ownership(), indent=2))
        baseline = runtime.wait_for()
        runtime.ping()
        runtime.save(baseline, output / "baseline")
        for name in ("pe1", "p", "pe2"):
            r = baseline["routers"][name]
            if r["mpls"].strip() == "enabled":
                # LDP must have at least one operational neighbor and a label table.
                if not runtime.ldp_ready(r["ldp"], r["labels"], 2 if name == "p" else 1):
                    raise RuntimeError(f"{name}: MPLS enabled but no operational LDP/label evidence")
        print("PASS baseline: OSPF, IS-IS, eBGP/iBGP, installed routes and bidirectional sourced ping", flush=True)
        for name in cases:
            try:
                runtime.apply_fault(name)
                # Wait for the protocol symptom as well as the physical/config change.
                import time
                time.sleep(6)
                broken = runtime.wait_for(name)
                runtime.save(broken, output / name / "fault")
                if name in ("link-down", "bgp-prefix-filter", "session-flap"):
                    if not runtime.customer_traffic_fails():
                        raise RuntimeError(f"{name}: fault did not interrupt customer traffic")
            finally:
                runtime.apply_fault(name, repair=True)
            repaired = runtime.wait_for()
            runtime.ping()
            runtime.save(repaired, output / name / "fixed")
            print(f"PASS {name}: evidence diagnosis and repair check", flush=True)
    finally:
        runtime.down()


def main():
    parser = argparse.ArgumentParser(description="Deploy, break, inspect and repair a five-router FRRouting lab")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("up")
    sub.add_parser("down")
    sub.add_parser("check")
    capture = sub.add_parser("collect")
    capture.add_argument("--output", default="artifacts/manual")
    for command in ("inject", "fix"):
        p = sub.add_parser(command)
        p.add_argument("case", choices=CASES)
    p = sub.add_parser("diagnose")
    p.add_argument("snapshot", type=Path)
    p = sub.add_parser("smoke")
    p.add_argument("--output", default="artifacts/smoke")
    p.add_argument("--case", choices=CASES, action="append")
    args = parser.parse_args()
    if args.command == "up":
        runtime.up()
        print(json.dumps(runtime.ownership(), indent=2))
    elif args.command == "down":
        runtime.down()
        print("Owned containers and networks removed; verified by Docker labels.")
    elif args.command == "check":
        data = runtime.wait_for()
        runtime.ping()
        print(markdown_report(data))
    elif args.command == "collect":
        data = runtime.collect()
        runtime.save(data, args.output)
        print(markdown_report(data))
    elif args.command in ("inject", "fix"):
        runtime.apply_fault(args.case, args.command == "fix")
    elif args.command == "diagnose":
        print(markdown_report(json.loads(args.snapshot.read_text())))
    else:
        smoke(args.output, args.case or list(CASES))


if __name__ == "__main__":
    main()
