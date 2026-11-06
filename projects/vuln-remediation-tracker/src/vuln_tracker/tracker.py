"""Transactional asset/CVE lifecycle with scanner-specific rescan evidence."""

import csv
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from .parsers import asset_id, parse_scan

SLA = {"critical": 7, "high": 14, "medium": 30, "low": 90, "none": 90, "unknown": 30}
SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
 id INTEGER PRIMARY KEY, source TEXT NOT NULL, scope TEXT NOT NULL, scanned_on TEXT NOT NULL,
 checksum TEXT NOT NULL, nvd_checksum TEXT NOT NULL, assets TEXT NOT NULL,
 complete_assets TEXT NOT NULL, unmapped INTEGER NOT NULL,
 UNIQUE(source,scope,checksum));
CREATE TABLE IF NOT EXISTS findings (
 asset TEXT NOT NULL, cve TEXT NOT NULL, score REAL, severity TEXT NOT NULL, vector TEXT,
 first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, due_date TEXT NOT NULL,
 status TEXT NOT NULL, owner TEXT NOT NULL DEFAULT '', validated_scan_id INTEGER,
 PRIMARY KEY(asset,cve), FOREIGN KEY(validated_scan_id) REFERENCES scans(id));
CREATE TABLE IF NOT EXISTS observations (
 asset TEXT NOT NULL, cve TEXT NOT NULL, source TEXT NOT NULL, scope TEXT NOT NULL,
 active INTEGER NOT NULL, last_scan_id INTEGER NOT NULL, evidence TEXT NOT NULL,
 PRIMARY KEY(asset,cve,source,scope), FOREIGN KEY(asset,cve) REFERENCES findings(asset,cve),
 FOREIGN KEY(last_scan_id) REFERENCES scans(id));
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, scan_id INTEGER NOT NULL, asset TEXT NOT NULL, cve TEXT NOT NULL,
 kind TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '[]', FOREIGN KEY(scan_id) REFERENCES scans(id));
CREATE TABLE IF NOT EXISTS activity (
 id INTEGER PRIMARY KEY, asset TEXT NOT NULL, cve TEXT NOT NULL, recorded_at TEXT NOT NULL,
 status TEXT NOT NULL, owner TEXT NOT NULL, due_date TEXT NOT NULL, note TEXT NOT NULL,
 FOREIGN KEY(asset,cve) REFERENCES findings(asset,cve));
PRAGMA user_version=1;
"""


def day(value):
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Dates must use YYYY-MM-DD")
    return parsed


def read_inventory(path):
    with Path(path).open(newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"asset", "name", "owner"} <= set(reader.fieldnames):
            raise ValueError("Inventory needs asset,name,owner columns")
        assets = {}
        for row in reader:
            asset = asset_id(row["asset"])
            if asset in assets:
                raise ValueError(f"Duplicate inventory asset: {asset}")
            assets[asset] = {"name": row["name"], "owner": row["owner"]}
    return assets


class Tracker:
    def __init__(self, path, snapshot):
        self.snapshot = snapshot
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        if self.db.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
            self.db.close()
            raise ValueError("Unsupported database schema version")
        self.db.executescript(SCHEMA)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def ingest(self, path, on, scope, complete_assets=()):
        scanned_on = day(on)
        if not scope.strip() or len(scope) > 100:
            raise ValueError("Scope must be 1 to 100 characters")
        scan = parse_scan(path)
        coverage = {asset_id(a) for a in complete_assets}
        if coverage and (not scan.complete or not coverage <= scan.assets):
            raise ValueError("Complete coverage requires a complete scan and live, present assets")
        counts = dict.fromkeys(("new", "recurring", "reopened", "fixed"), 0)
        with self.db:
            # Serialize writers before checking duplicate/order constraints.
            self.db.execute("BEGIN IMMEDIATE")
            duplicate = self.db.execute(
                "SELECT id FROM scans WHERE source=? AND scope=? AND checksum=?",
                (scan.source, scope, scan.checksum),
            ).fetchone()
            if duplicate:
                return {"scan_id": duplicate["id"], "duplicate": True, **counts}
            latest = self.db.execute("SELECT max(scanned_on) FROM scans").fetchone()[0]
            if latest and on < latest:
                raise ValueError("Imports must be chronological across this database")
            cursor = self.db.execute(
                "INSERT INTO scans(source,scope,scanned_on,checksum,nvd_checksum,assets,"
                "complete_assets,unmapped) VALUES(?,?,?,?,?,?,?,?)",
                (
                    scan.source,
                    scope,
                    on,
                    scan.checksum,
                    self.snapshot.checksum,
                    json.dumps(sorted(scan.assets)),
                    json.dumps(sorted(coverage)),
                    scan.unmapped,
                ),
            )
            scan_id = cursor.lastrowid
            seen = set()
            for finding in scan.findings:
                key = (finding.asset, finding.cve)
                seen.add(key)
                old = self.db.execute(
                    "SELECT * FROM findings WHERE asset=? AND cve=?", key
                ).fetchone()
                info = self.snapshot.lookup(finding.cve)
                due = (scanned_on + timedelta(days=SLA[info["severity"]])).isoformat()
                if old is None:
                    kind = "new"
                    self.db.execute(
                        "INSERT INTO findings(asset,cve,score,severity,vector,first_seen,last_seen,"
                        "due_date,status) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            *key,
                            info["score"],
                            info["severity"],
                            info["vector"],
                            on,
                            on,
                            due,
                            "open",
                        ),
                    )
                else:
                    kind = "reopened" if old["status"] == "fixed" else "recurring"
                    self.db.execute(
                        "UPDATE findings SET last_seen=?,score=?,severity=?,vector=?,"
                        "due_date=?,status=?,validated_scan_id=NULL WHERE asset=? AND cve=?",
                        (
                            on,
                            info["score"],
                            info["severity"],
                            info["vector"],
                            due if kind == "reopened" else old["due_date"],
                            "open" if kind == "reopened" else old["status"],
                            *key,
                        ),
                    )
                self.db.execute(
                    "INSERT INTO observations VALUES(?,?,?,?,1,?,?) "
                    "ON CONFLICT(asset,cve,source,scope) DO UPDATE SET active=1,"
                    "last_scan_id=excluded.last_scan_id,evidence=excluded.evidence",
                    (*key, scan.source, scope, scan_id, json.dumps(finding.evidence)),
                )
                self.db.execute(
                    "INSERT INTO events(scan_id,asset,cve,kind,evidence) VALUES(?,?,?,?,?)",
                    (scan_id, *key, kind, json.dumps(finding.evidence)),
                )
                counts[kind] += 1
            prior = self.db.execute(
                "SELECT asset,cve FROM observations WHERE source=? AND scope=? AND active=1",
                (scan.source, scope),
            ).fetchall()
            for row in prior:
                key = (row["asset"], row["cve"])
                if row["asset"] not in coverage or key in seen:
                    continue
                self.db.execute(
                    "UPDATE observations SET active=0,last_scan_id=? "
                    "WHERE asset=? AND cve=? AND source=? AND scope=?",
                    (scan_id, *key, scan.source, scope),
                )
                active = self.db.execute(
                    "SELECT count(*) FROM observations WHERE asset=? AND cve=? AND active=1", key
                ).fetchone()[0]
                if not active:
                    self.db.execute(
                        "UPDATE findings SET status='fixed',validated_scan_id=? WHERE asset=? AND cve=?",
                        (scan_id, *key),
                    )
                    self.db.execute(
                        "INSERT INTO events(scan_id,asset,cve,kind) VALUES(?,?,?,?)",
                        (scan_id, *key, "fixed"),
                    )
                    counts["fixed"] += 1
        return {"scan_id": scan_id, "duplicate": False, "unmapped": scan.unmapped, **counts}

    def update(self, asset, cve, status, *, owner=None, note="", due_date=None):
        asset = asset_id(asset)
        if status not in ("open", "in_progress", "pending_validation"):
            raise ValueError("Invalid manual status; fixed requires a complete rescan")
        if not note.strip() or len(note) > 2000 or (owner is not None and len(owner) > 200):
            raise ValueError(
                "A note of 1 to 2000 characters and owner up to 200 characters are required"
            )
        if due_date:
            day(due_date)
        with self.db:
            row = self.db.execute(
                "SELECT * FROM findings WHERE asset=? AND cve=?", (asset, cve)
            ).fetchone()
            if row is None:
                raise ValueError("Unknown finding")
            if row["status"] == "fixed":
                raise ValueError("Fixed finding can only reopen through scan evidence")
            due = due_date or row["due_date"]
            owner = row["owner"] if owner is None else owner
            self.db.execute(
                "UPDATE findings SET status=?,owner=?,due_date=? WHERE asset=? AND cve=?",
                (status, owner, due, asset, cve),
            )
            self.db.execute(
                "INSERT INTO activity(asset,cve,recorded_at,status,owner,due_date,note) "
                "VALUES(?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),?,?,?,?)",
                (asset, cve, status, owner, due, note),
            )

    def report(self, as_of, inventory=None):
        day(as_of)
        findings = []
        for row in self.db.execute("SELECT * FROM findings ORDER BY asset,cve"):
            item = dict(row)
            key = (row["asset"], row["cve"])
            item["overdue"] = item["status"] != "fixed" and item["due_date"] < as_of
            item["observations"] = []
            for obs in self.db.execute(
                "SELECT * FROM observations WHERE asset=? AND cve=? ORDER BY source,scope", key
            ):
                observation = dict(obs)
                observation["evidence"] = json.loads(observation["evidence"])
                item["observations"].append(observation)
            item["history"] = [
                dict(e)
                for e in self.db.execute(
                    "SELECT events.*,scans.scanned_on FROM events JOIN scans ON scans.id=events.scan_id "
                    "WHERE asset=? AND cve=? ORDER BY events.id",
                    key,
                )
            ]
            for event in item["history"]:
                event["evidence"] = json.loads(event["evidence"])
            item["activity"] = [
                dict(a)
                for a in self.db.execute(
                    "SELECT * FROM activity WHERE asset=? AND cve=? ORDER BY id", key
                )
            ]
            findings.append(item)
        latest = self.db.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        summary = {
            "scans": self.db.execute("SELECT count(*) FROM scans").fetchone()[0],
            "active": sum(f["status"] != "fixed" for f in findings),
            "fixed": sum(f["status"] == "fixed" for f in findings),
            "overdue": sum(f["overdue"] for f in findings),
            "unknown_severity": sum(f["severity"] == "unknown" for f in findings),
        }
        events = (
            []
            if latest is None
            else [
                dict(e)
                for e in self.db.execute(
                    "SELECT asset,cve,kind FROM events WHERE scan_id=? ORDER BY id", (latest["id"],)
                )
            ]
        )
        result = {
            "as_of": as_of,
            "summary": summary,
            "findings": findings,
            "latest_scan": dict(latest) if latest else None,
            "latest_events": events,
        }
        if inventory:
            expected = read_inventory(inventory)
            observed = set(json.loads(latest["assets"])) if latest else set()
            result["inventory"] = {
                "scan_id": latest["id"] if latest else None,
                "matched": sorted(observed & expected.keys()),
                "missing": sorted(expected.keys() - observed),
                "unexpected": sorted(observed - expected.keys()),
            }
        return result
