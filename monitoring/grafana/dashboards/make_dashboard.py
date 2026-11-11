"""Write home-server.json, the Grafana dashboard that is provisioned from this folder.

Run `python monitoring/grafana/dashboards/make_dashboard.py` after changing a panel.
The test in monitoring/tests checks that the committed JSON matches this script.
"""

import json
from pathlib import Path

DATASOURCE = {"type": "prometheus", "uid": "prometheus"}
OUT = Path(__file__).with_name("home-server.json")


def stat(panel_id, title, expr, x, y, w=6, unit="none", thresholds=None, legend="{{instance}}"):
    return {
        "id": panel_id,
        "type": "stat",
        "title": title,
        "datasource": DATASOURCE,
        "gridPos": {"x": x, "y": y, "w": w, "h": 5},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "thresholds": {"mode": "absolute", "steps": thresholds or [{"color": "green", "value": None}]},
            },
            "overrides": [],
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
        "targets": [{"refId": "A", "datasource": DATASOURCE, "expr": expr, "legendFormat": legend}],
    }


def series(panel_id, title, exprs, x, y, w=12, unit="none", h=8):
    return {
        "id": panel_id,
        "type": "timeseries",
        "title": title,
        "datasource": DATASOURCE,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
        "targets": [
            {"refId": chr(65 + i), "datasource": DATASOURCE, "expr": expr, "legendFormat": legend}
            for i, (expr, legend) in enumerate(exprs)
        ],
    }


def row(panel_id, title, y):
    return {"id": panel_id, "type": "row", "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


DISK = 'fstype!~"tmpfs|overlay|squashfs|vfat"'
RED_BELOW_10 = [{"color": "red", "value": None}, {"color": "orange", "value": 0.10}, {"color": "green", "value": 0.25}]
UP_OR_DOWN = [{"color": "red", "value": None}, {"color": "green", "value": 1}]

PANELS = [
    row(100, "Availability", 0),
    stat(1, "LifeOS demo reachable", 'probe_success{job="lifeos-demo"}', 0, 1, unit="none",
         thresholds=UP_OR_DOWN, legend="demo"),
    stat(2, "LifeOS health check", 'probe_success{job="lifeos-health"}', 6, 1,
         thresholds=UP_OR_DOWN, legend="health"),
    stat(3, "Scrape targets up", 'count(up == 1) / count(up)', 12, 1, unit="percentunit",
         thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 0.8},
                     {"color": "green", "value": 1}], legend="targets"),
    stat(4, "Days until TLS certificate expires",
         '(probe_ssl_earliest_cert_expiry{job=~"lifeos.*"} - time()) / 86400', 18, 1, unit="d",
         thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 14},
                     {"color": "green", "value": 30}], legend="{{instance}}"),
    series(5, "LifeOS response time", [
        ('probe_duration_seconds{job="lifeos-demo"}', "demo"),
        ('probe_duration_seconds{job="lifeos-health"}', "health"),
    ], 0, 6, unit="s"),
    row(101, "Performance", 14),
    series(6, "CPU busy", [
        ('100 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100', "{{instance}}"),
    ], 0, 15, unit="percent"),
    series(7, "Load average (1 minute)", [("node_load1", "{{instance}}")], 12, 15),
    series(8, "Memory used", [
        ("100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)", "{{instance}}"),
    ], 0, 23, unit="percent"),
    series(9, "Probe duration by check", [
        ('probe_http_duration_seconds{job="lifeos-demo"}', "demo"),
    ], 12, 23, unit="s"),
    row(102, "Disk capacity and backups", 31),
    series(10, "Disk used by mount", [
        (f"100 * (1 - node_filesystem_avail_bytes{{{DISK}}} / node_filesystem_size_bytes{{{DISK}}})",
         "{{instance}} {{mountpoint}}"),
    ], 0, 32, unit="percent"),
    series(11, "Time until each disk is full at the current trend", [
        (f"(node_filesystem_avail_bytes{{{DISK}}} / (-deriv(node_filesystem_avail_bytes{{{DISK}}}[6h]) > 0))"
         " / 86400", "{{instance}} {{mountpoint}}"),
    ], 12, 32, unit="d"),
    stat(12, "Hours since last good backup",
         "(time() - home_ops_backup_last_success_timestamp_seconds) / 3600", 0, 40, w=8, unit="h",
         thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 24},
                     {"color": "red", "value": 26}], legend="{{database}}"),
    stat(13, "Disks below 10% free", f"count(node_filesystem_avail_bytes{{{DISK}}} / "
         f"node_filesystem_size_bytes{{{DISK}}} < 0.10) or vector(0)", 8, 40, w=8,
         thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}], legend="disks"),
    stat(14, "Active alerts", 'count(ALERTS{alertstate="firing"}) or vector(0)', 16, 40, w=8,
         thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}], legend="firing"),
]


def build():
    return {
        "uid": "home-server",
        "title": "Home server",
        "tags": ["home-server"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "1m",
        "time": {"from": "now-6h", "to": "now"},
        "panels": PANELS,
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
