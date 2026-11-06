"""CLI commands; all machine-readable output is JSON when requested."""

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

from .nvd import load_snapshot
from .tracker import Tracker


def data_directory():
    packaged = Path(__file__).parent / "data"
    return packaged if packaged.exists() else Path(__file__).resolve().parents[2] / "data"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Track scan findings through rescan-validated fixes"
    )
    parser.add_argument("--db", default="tracker.sqlite", help="SQLite database path")
    parser.add_argument("--snapshot", type=Path, default=data_directory() / "nvd-snapshot.json")
    parser.add_argument("--manifest", type=Path, default=data_directory() / "nvd-manifest.json")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Import Nmap or Greenbone XML")
    ingest.add_argument("scan", type=Path)
    ingest.add_argument("--scope", required=True, help="Stable name for this scanner configuration")
    ingest.add_argument("--on", default=date.today().isoformat(), help="Scan date, YYYY-MM-DD")
    ingest.add_argument(
        "--complete-asset",
        action="append",
        default=[],
        metavar="IP",
        help="Assert all relevant checks/ports were rerun for this live asset",
    )
    update = commands.add_parser("update", help="Assign work or request validation of a fix")
    update.add_argument("asset")
    update.add_argument("cve")
    update.add_argument(
        "--status", required=True, choices=["open", "in_progress", "pending_validation"]
    )
    update.add_argument("--owner", default=None)
    update.add_argument("--due-date")
    update.add_argument("--note", required=True)
    report = commands.add_parser("report", help="Show findings, recent changes, and inventory gaps")
    report.add_argument(
        "--as-of", default=date.today().isoformat(), help="Overdue cutoff, YYYY-MM-DD"
    )
    report.add_argument("--inventory", type=Path)
    report.add_argument(
        "--strict-inventory", action="store_true", help="Exit 3 if inventory differs"
    )
    report.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)
    try:
        if args.command == "report" and args.strict_inventory and not args.inventory:
            raise ValueError("--strict-inventory requires --inventory")
        snapshot = load_snapshot(args.snapshot, args.manifest)
        with Tracker(args.db, snapshot) as tracker:
            if args.command == "ingest":
                result = tracker.ingest(args.scan, args.on, args.scope, args.complete_asset)
            elif args.command == "update":
                tracker.update(
                    args.asset,
                    args.cve,
                    args.status,
                    owner=args.owner,
                    note=args.note,
                    due_date=args.due_date,
                )
                result = {"asset": args.asset, "cve": args.cve, "status": args.status}
            else:
                result = tracker.report(args.as_of, args.inventory)
        if args.command == "report" and args.format == "text":
            print("Current findings (overdue cutoff: " + result["as_of"] + ")")
            print("  ".join(f"{k}: {v}" for k, v in result["summary"].items()))
            for f in result["findings"]:
                print(
                    f"{f['asset']:16} {f['cve']:20} {f['severity']:8} {f['status']:18} "
                    f"due {f['due_date']} {'OVERDUE' if f['overdue'] else ''} owner={f['owner']}"
                )
            print("Latest scan changes: " + json.dumps(result["latest_events"]))
            if "inventory" in result:
                print("Inventory against latest scan: " + json.dumps(result["inventory"]))
        else:
            print(json.dumps(result, indent=2))
        if args.command == "report" and args.strict_inventory:
            if result["inventory"]["missing"] or result["inventory"]["unexpected"]:
                return 3
        return 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
