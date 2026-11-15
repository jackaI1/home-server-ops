"""Parse the generated files back in Python to check their structure.

These parsers only accept the keys that render.py writes. An unknown key is an error, which catches
a typo before a service refuses to start on the box.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

HOSTAPD_KEYS = {
    "interface", "driver", "ssid", "country_code", "hw_mode", "channel", "ieee80211n", "wpa",
    "wpa_key_mgmt", "rsn_pairwise", "wpa_passphrase", "macaddr_acl", "accept_mac_file", "ap_isolate",
}
HOSTAPD_REQUIRED = {"interface", "driver", "ssid", "hw_mode", "channel", "wpa", "wpa_key_mgmt",
                    "rsn_pairwise", "wpa_passphrase", "macaddr_acl", "accept_mac_file"}
DNSMASQ_FLAGS = {"bind-interfaces", "no-resolv", "no-hosts", "dhcp-authoritative"}
DNSMASQ_KEYS = {"interface", "port", "dhcp-range", "dhcp-option", "dhcp-host", "dhcp-ignore",
                "dhcp-leasefile", "pid-file"}


class ParseError(ValueError):
    pass


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def parse_hostapd(text: str) -> dict[str, str]:
    """Return key=value pairs from a hostapd.conf. Duplicate or unknown keys are errors."""
    result: dict[str, str] = {}
    for line in _lines(text):
        if "=" not in line:
            raise ParseError(f"hostapd line has no '=': {line!r}")
        key, value = line.split("=", 1)
        if key not in HOSTAPD_KEYS:
            raise ParseError(f"unknown hostapd key: {key}")
        if key in result:
            raise ParseError(f"duplicate hostapd key: {key}")
        result[key] = value
    missing = HOSTAPD_REQUIRED - result.keys()
    if missing:
        raise ParseError(f"hostapd config is missing: {', '.join(sorted(missing))}")
    if result["wpa"] != "2" or result["rsn_pairwise"] != "CCMP":
        raise ParseError("hostapd must use WPA2 with CCMP")
    if result["macaddr_acl"] != "1":
        raise ParseError("hostapd must use an accept list (macaddr_acl=1)")
    if not 8 <= len(result["wpa_passphrase"]) <= 63:
        raise ParseError("wpa_passphrase must be 8 to 63 characters")
    return result


def parse_dnsmasq(text: str) -> list[tuple[str, str]]:
    """Return (option, value) pairs. Value is '' for bare flags. Each dhcp-host must carry a known MAC and IP."""
    entries: list[tuple[str, str]] = []
    for line in _lines(text):
        if "=" in line:
            key, value = line.split("=", 1)
        else:
            key, value = line, ""
        if key not in DNSMASQ_KEYS and key not in DNSMASQ_FLAGS:
            raise ParseError(f"unknown dnsmasq option: {key}")
        if key == "dhcp-host":
            parts = value.split(",")
            if len(parts) < 2:
                raise ParseError(f"dhcp-host needs a MAC and an IP: {value!r}")
            ipaddress.IPv4Address(parts[1])
        if key == "dhcp-range":
            ipaddress.IPv4Address(value.split(",")[0])
        entries.append((key, value))
    return entries


def parse_accept_file(text: str) -> list[str]:
    macs = [line.strip() for line in text.splitlines() if line.strip()]
    for mac in macs:
        if len(mac.split(":")) != 6:
            raise ParseError(f"accept file has a bad MAC: {mac}")
    if len(set(macs)) != len(macs):
        raise ParseError("accept file lists a MAC twice")
    return macs


def read_and_parse(directory: str | Path) -> dict:
    """Parse every file rendered into directory. Used by the CLI check command and the tests."""
    base = Path(directory)
    hostapd = parse_hostapd((base / "hostapd.conf").read_text())
    dnsmasq = parse_dnsmasq((base / "dnsmasq.conf").read_text())
    accept = parse_accept_file((base / "hostapd.accept").read_text())
    return {"hostapd": hostapd, "dnsmasq": dnsmasq, "accept": accept}
