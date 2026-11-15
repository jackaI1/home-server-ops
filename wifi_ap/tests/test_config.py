import copy
from pathlib import Path

import pytest
import yaml

from wifi_ap.config import ConfigError, load_config, parse_config

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "example.yaml"


def base() -> dict:
    return copy.deepcopy(yaml.safe_load(EXAMPLE.read_text()))


def test_example_loads_and_has_two_devices():
    cfg = load_config(EXAMPLE)
    assert cfg.ssid == "lifeos-desk"
    assert [d.name for d in cfg.devices] == ["desk-node", "garden-sensor"]
    assert str(cfg.gateway) == "10.77.0.1"
    assert cfg.only_known_devices is True


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["ap"].update(ssid="x" * 33), "ssid"),
        (lambda d: d["ap"].update(channel=14), "channel"),
        (lambda d: d["ap"].update(country_code="XX"), "country_code"),
        (lambda d: d.update(subnet="10.77.0.5/24"), "subnet"),
        (lambda d: d.update(gateway="10.88.0.1"), "gateway"),
        (lambda d: d["dhcp"].update(range="10.77.0.100-10.77.0.50"), "dhcp.range"),
        (lambda d: d["dhcp"].update(range="10.77.0.1-10.77.0.20"), "gateway"),
        (lambda d: d["dhcp"].update(lease_time="forever"), "lease_time"),
        (lambda d: d["sensor_endpoint"].update(address="10.77.0.9"), "sensor_endpoint"),
        (lambda d: d["sensor_endpoint"].update(port=70000), "port"),
        (lambda d: d["devices"][0].update(mac="00:00:00:00:00:09"), "locally administered"),
        (lambda d: d["devices"][0].update(mac="02:00:00:00:00:GG"), "mac"),
        (lambda d: d["devices"][0].update(ip="10.77.0.120"), "outside dhcp.range"),
        (lambda d: d["devices"][1].update(ip="10.77.0.50"), "used twice"),
        (lambda d: d["devices"][1].update(name="desk-node"), "used twice"),
        (lambda d: d["devices"][0].update(ip="10.77.0.1"), "gateway"),
        (lambda d: d.update(devices=[]), "devices"),
        (lambda d: d["devices"][0].update(extra=1), "unknown key"),
        (lambda d: d.update(vpn={"enabled": True}), "unknown key"),
        (lambda d: d["uplink"].update(interface="wlan0"), "different"),
    ],
)
def test_bad_values_are_rejected_with_the_key_named(mutate, message):
    data = base()
    mutate(data)
    with pytest.raises(ConfigError) as info:
        parse_config(data)
    assert message in str(info.value)


def test_missing_section_is_reported():
    data = base()
    del data["sensor_endpoint"]
    with pytest.raises(ConfigError, match="missing 'sensor_endpoint'"):
        parse_config(data)


def test_bad_yaml_file_is_a_config_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("ap: [unclosed\n")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(bad)
