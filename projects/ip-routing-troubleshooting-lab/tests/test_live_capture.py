"""Regression input captured from the public, real-container CI run 42172316938."""
import json
from pathlib import Path

from routing_lab.diagnosis import bgp_peers, installed_bgp, ospf_states, parse_json
from routing_lab.runtime import ldp_ready


def test_parsers_accept_captured_frr_10_2_1_output():
    raw = json.loads((Path(__file__).parent / "fixtures/frr-10.2.1-pe1.json").read_text())
    assert ospf_states(raw["ospf"]) == ["Full/-"]
    peers = bgp_peers(raw["bgp"])
    assert set(peers) == {"10.10.1.2", "10.255.0.2", "10.255.0.3"}
    assert all(p["state"] == "Established" for p in peers.values())
    routes = parse_json(raw["routes"])
    assert installed_bgp(routes, "198.18.1.0/24")
    assert installed_bgp(routes, "198.18.2.0/24")
    assert ldp_ready(raw["ldp"], raw["labels"], 1)
