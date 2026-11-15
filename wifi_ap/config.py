"""Load and check the access point YAML file.

Every rule here exists so a typo fails loudly at render time instead of producing a
network that quietly lets devices onto the home LAN.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
IFACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,14}$")
LEASE_RE = re.compile(r"^(\d+[hm]|infinite)$")

# Channels allowed for 2.4 GHz (hw_mode g) by the country. Other countries are rejected on purpose.
CHANNELS_BY_COUNTRY = {"CA": range(1, 12), "US": range(1, 12), "GB": range(1, 14), "DE": range(1, 14)}

TOP_KEYS = {"ap", "uplink", "subnet", "gateway", "dhcp", "sensor_endpoint", "devices"}


class ConfigError(ValueError):
    """Raised with a message that names the bad key."""


@dataclass(frozen=True)
class Device:
    name: str
    mac: str
    ip: ipaddress.IPv4Address


@dataclass(frozen=True)
class Config:
    ssid: str
    country_code: str
    channel: int
    ap_interface: str
    uplink_interface: str
    subnet: ipaddress.IPv4Network
    gateway: ipaddress.IPv4Address
    dhcp_start: ipaddress.IPv4Address
    dhcp_end: ipaddress.IPv4Address
    lease_time: str
    only_known_devices: bool
    sensor_ip: ipaddress.IPv4Address
    sensor_port: int
    devices: tuple[Device, ...]


def _require_mapping(value: Any, where: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping")
    return value


def _reject_unknown(section: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ConfigError(f"{where} has unknown key(s): {', '.join(unknown)}")


def _ipv4(value: Any, where: str) -> ipaddress.IPv4Address:
    try:
        return ipaddress.IPv4Address(str(value))
    except ValueError as exc:
        raise ConfigError(f"{where} is not an IPv4 address: {value!r}") from exc


def _iface(value: Any, where: str) -> str:
    if not isinstance(value, str) or not IFACE_RE.match(value):
        raise ConfigError(f"{where} is not a valid interface name: {value!r}")
    return value


def parse_config(data: Any) -> Config:
    """Validate a parsed YAML document and return a Config. Raises ConfigError."""
    root = _require_mapping(data, "config")
    _reject_unknown(root, TOP_KEYS, "config")
    for key in TOP_KEYS:
        if key not in root:
            raise ConfigError(f"config is missing '{key}'")

    ap = _require_mapping(root["ap"], "ap")
    _reject_unknown(ap, {"ssid", "country_code", "channel", "ap_interface"}, "ap")
    ssid = ap["ssid"]
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32:
        raise ConfigError("ap.ssid must be 1 to 32 bytes")
    country = ap["country_code"]
    if country not in CHANNELS_BY_COUNTRY:
        raise ConfigError(f"ap.country_code must be one of {sorted(CHANNELS_BY_COUNTRY)}")
    channel = ap["channel"]
    if not isinstance(channel, int) or channel not in CHANNELS_BY_COUNTRY[country]:
        raise ConfigError(f"ap.channel {channel!r} is not allowed in {country}")
    ap_iface = _iface(ap["ap_interface"], "ap.ap_interface")

    uplink = _require_mapping(root["uplink"], "uplink")
    _reject_unknown(uplink, {"interface"}, "uplink")
    uplink_iface = _iface(uplink["interface"], "uplink.interface")
    if uplink_iface == ap_iface:
        raise ConfigError("uplink.interface and ap.ap_interface must be different")

    try:
        subnet = ipaddress.IPv4Network(str(root["subnet"]), strict=True)
    except ValueError as exc:
        raise ConfigError(f"subnet is not a valid network: {root['subnet']!r}") from exc
    if subnet.prefixlen > 28:
        raise ConfigError("subnet must be /28 or larger")
    gateway = _ipv4(root["gateway"], "gateway")
    if gateway not in subnet or gateway in (subnet.network_address, subnet.broadcast_address):
        raise ConfigError("gateway must be a usable address inside subnet")

    dhcp = _require_mapping(root["dhcp"], "dhcp")
    _reject_unknown(dhcp, {"range", "lease_time", "only_known_devices"}, "dhcp")
    rng = str(dhcp.get("range", ""))
    if "-" not in rng:
        raise ConfigError("dhcp.range must look like 10.0.0.100-10.0.0.199")
    start_s, end_s = (part.strip() for part in rng.split("-", 1))
    start, end = _ipv4(start_s, "dhcp.range start"), _ipv4(end_s, "dhcp.range end")
    if not (start in subnet and end in subnet and start <= end):
        raise ConfigError("dhcp.range must be inside subnet and in order")
    if start <= gateway <= end:
        raise ConfigError("dhcp.range must not contain the gateway")
    lease = str(dhcp.get("lease_time", "12h"))
    if not LEASE_RE.match(lease):
        raise ConfigError("dhcp.lease_time must look like 12h, 30m or infinite")
    only_known = dhcp.get("only_known_devices", True)
    if not isinstance(only_known, bool):
        raise ConfigError("dhcp.only_known_devices must be true or false")

    sensor = _require_mapping(root["sensor_endpoint"], "sensor_endpoint")
    _reject_unknown(sensor, {"address", "port"}, "sensor_endpoint")
    sensor_ip = _ipv4(sensor["address"], "sensor_endpoint.address")
    if sensor_ip in subnet:
        raise ConfigError("sensor_endpoint must be on the home network, not inside subnet")
    port = sensor["port"]
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigError("sensor_endpoint.port must be 1 to 65535")

    raw_devices = root["devices"]
    if not isinstance(raw_devices, list) or not raw_devices:
        raise ConfigError("devices must be a non-empty list")
    devices: list[Device] = []
    seen: dict[str, set[str]] = {"name": set(), "mac": set(), "ip": set()}
    for index, item in enumerate(raw_devices):
        where = f"devices[{index}]"
        dev = _require_mapping(item, where)
        _reject_unknown(dev, {"name", "mac", "ip"}, where)
        name, mac = dev.get("name"), str(dev.get("mac", "")).lower()
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ConfigError(f"{where}.name must be lowercase letters, digits and dashes")
        if not MAC_RE.match(mac):
            raise ConfigError(f"{where}.mac must look like 02:00:00:00:00:01")
        if not mac.startswith(("02:", "06:", "0a:", "0e:")):
            raise ConfigError(f"{where}.mac must be locally administered (first byte ends in 2, 6, a or e)")
        ip = _ipv4(dev.get("ip"), f"{where}.ip")
        if ip not in subnet or ip in (subnet.network_address, subnet.broadcast_address, gateway):
            raise ConfigError(f"{where}.ip must be a host address inside subnet, not the gateway")
        if start <= ip <= end:
            raise ConfigError(f"{where}.ip must be outside dhcp.range so it is never handed out twice")
        for field_name, value in (("name", name), ("mac", mac), ("ip", str(ip))):
            if value in seen[field_name]:
                raise ConfigError(f"{where}.{field_name} {value} is used twice")
            seen[field_name].add(value)
        devices.append(Device(name=name, mac=mac, ip=ip))

    return Config(
        ssid=ssid,
        country_code=country,
        channel=channel,
        ap_interface=ap_iface,
        uplink_interface=uplink_iface,
        subnet=subnet,
        gateway=gateway,
        dhcp_start=start,
        dhcp_end=end,
        lease_time=lease,
        only_known_devices=only_known,
        sensor_ip=sensor_ip,
        sensor_port=port,
        devices=tuple(devices),
    )



def load_config(path: str | Path) -> Config:
    """Read a YAML file from disk and validate it."""
    try:
        data = yaml.safe_load(Path(path).read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    return parse_config(data)
