import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "wifi_ap" / "examples" / "example.yaml"


def run(*args, env=None):
    merged = {**os.environ, **(env or {})}
    return subprocess.run([sys.executable, "-m", "wifi_ap", *args], cwd=ROOT, env=merged,
                          capture_output=True, text=True)


def test_check_prints_summary():
    result = run("check", str(EXAMPLE))
    assert result.returncode == 0, result.stderr
    assert "ssid=lifeos-desk" in result.stdout


def test_render_then_verify_round_trip(tmp_path):
    out = tmp_path / "conf"
    result = run("render", str(EXAMPLE), "--out", str(out), "--state-dir", str(tmp_path),
                 env={"WIFI_AP_PASSPHRASE": "correct-horse-battery"})
    assert result.returncode == 0, result.stderr
    verify = run("verify", str(out))
    assert verify.returncode == 0, verify.stderr
    assert "devices=2" in verify.stdout


def test_render_without_passphrase_fails_cleanly(tmp_path):
    env = {"WIFI_AP_PASSPHRASE": ""}
    result = run("render", str(EXAMPLE), "--out", str(tmp_path / "c"), env=env)
    assert result.returncode == 1
    assert "error:" in result.stderr


def test_bad_config_exits_one(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(EXAMPLE.read_text().replace("channel: 6", "channel: 14"))
    result = run("check", str(bad))
    assert result.returncode == 1
    assert "channel" in result.stderr
