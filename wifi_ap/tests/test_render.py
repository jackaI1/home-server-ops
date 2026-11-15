from pathlib import Path

import pytest

from wifi_ap.config import load_config
from wifi_ap.parsers import ParseError, parse_accept_file, parse_dnsmasq, parse_hostapd, read_and_parse
from wifi_ap.render import RenderError, render_all, render_dnsmasq, render_hostapd, render_nftables

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "example.yaml"
PASS = "correct-horse-battery"


@pytest.fixture()
def cfg():
    return load_config(EXAMPLE)


def test_render_all_writes_four_files_and_they_parse_back(cfg, tmp_path):
    written = render_all(cfg, PASS, tmp_path / "out", state_dir="/var/lib/wifi-ap")
    assert sorted(p.name for p in written.values()) == [
        "dnsmasq.conf", "hostapd.accept", "hostapd.conf", "nftables.nft"]
    summary = read_and_parse(tmp_path / "out")
    assert summary["hostapd"]["ssid"] == "lifeos-desk"
    assert summary["accept"] == ["02:00:00:00:00:01", "02:00:00:00:00:02"]


def test_hostapd_file_is_private_and_holds_the_passphrase(cfg, tmp_path):
    written = render_all(cfg, PASS, tmp_path / "out", state_dir="/tmp/x")
    assert written["hostapd.conf"].stat().st_mode & 0o777 == 0o600
    assert written["dnsmasq.conf"].stat().st_mode & 0o777 == 0o644
    assert f"wpa_passphrase={PASS}" in written["hostapd.conf"].read_text()
    assert PASS not in written["dnsmasq.conf"].read_text()


def test_hostapd_uses_wpa2_accept_list_and_isolation(cfg):
    parsed = parse_hostapd(render_hostapd(cfg, PASS, "/etc/wifi-ap/hostapd.accept"))
    assert parsed["wpa"] == "2"
    assert parsed["rsn_pairwise"] == "CCMP"
    assert parsed["macaddr_acl"] == "1"
    assert parsed["ap_isolate"] == "1"
    assert parsed["accept_mac_file"] == "/etc/wifi-ap/hostapd.accept"
    assert parsed["channel"] == "6"


@pytest.mark.parametrize("passphrase", ["short", "x" * 64, "has\nnewline1"])
def test_hostapd_rejects_bad_passphrases(cfg, passphrase):
    with pytest.raises(RenderError):
        render_hostapd(cfg, passphrase, "/x")


def test_dnsmasq_has_static_leases_separate_range_and_known_only(cfg):
    text = render_dnsmasq(cfg, "/var/lib/wifi-ap")
    entries = parse_dnsmasq(text)
    assert ("dhcp-host", "02:00:00:00:00:01,10.77.0.50,desk-node,set:known") in entries
    assert ("dhcp-range", "10.77.0.100,10.77.0.199,12h") in entries
    assert ("dhcp-ignore", "tag:!known") in entries
    assert ("dhcp-option", "option:router,10.77.0.1") in entries
    assert ("port", "0") in entries


def test_dnsmasq_can_allow_unknown_devices(cfg):
    from dataclasses import replace
    text = render_dnsmasq(replace(cfg, only_known_devices=False), "/var/lib/wifi-ap")
    assert "dhcp-ignore" not in text


def test_nftables_only_opens_the_sensor_port(cfg):
    text = render_nftables(cfg)
    assert "ip daddr 192.168.50.10 tcp dport 8080 accept" in text
    assert "type filter hook forward priority filter; policy drop;" in text
    assert "masquerade" in text
    assert "10.77.0.0/24" in text
    # Only one accept rule may reach the home side.
    forward_accepts = [line for line in text.splitlines() if "oifname" in line and "accept" in line]
    assert len(forward_accepts) == 1


def test_parser_rejects_unknown_and_duplicate_keys():
    with pytest.raises(ParseError, match="unknown hostapd key"):
        parse_hostapd("interface=wlan0\nbogus=1\n")
    good = "interface=wlan0\ndriver=nl80211\nssid=a\nhw_mode=g\nchannel=1\nwpa=2\nwpa_key_mgmt=WPA-PSK\n" \
           "rsn_pairwise=CCMP\nwpa_passphrase=abcdefgh\nmacaddr_acl=1\naccept_mac_file=/x\n"
    parse_hostapd(good)
    with pytest.raises(ParseError, match="duplicate"):
        parse_hostapd(good + "ssid=b\n")
    with pytest.raises(ParseError, match="missing"):
        parse_hostapd("interface=wlan0\n")
    with pytest.raises(ParseError, match="unknown dnsmasq option"):
        parse_dnsmasq("dhcp-hots=1\n")
    with pytest.raises(ParseError, match="accept list"):
        parse_hostapd(good.replace("macaddr_acl=1", "macaddr_acl=0"))


def test_accept_file_rejects_duplicates_and_bad_macs():
    assert parse_accept_file("02:00:00:00:00:01\n") == ["02:00:00:00:00:01"]
    with pytest.raises(ParseError):
        parse_accept_file("02:00:00:00:00:01\n02:00:00:00:00:01\n")
    with pytest.raises(ParseError):
        parse_accept_file("02:00:00:01\n")


def test_missing_passphrase_env_is_an_error(monkeypatch):
    from wifi_ap.render import passphrase_from_env
    monkeypatch.delenv("WIFI_AP_PASSPHRASE", raising=False)
    with pytest.raises(RenderError, match="never stored in the YAML"):
        passphrase_from_env()
