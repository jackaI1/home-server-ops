import copy
import json

import pytest

from routing_lab.diagnosis import diagnose, parse_json, bgp_peers, ospf_states


def healthy():
    """Hand-written input matching FRR's command output shapes, not a case label."""
    routers = {}
    peers = {"ce1": ["10.10.1.3"], "pe1": ["10.10.1.2", "10.255.0.2", "10.255.0.3"],
             "p": ["10.255.0.1", "10.255.0.3"],
             "pe2": ["10.10.4.3", "10.255.0.1", "10.255.0.2"], "ce2": ["10.10.4.2"]}
    for name, addresses in peers.items():
        access = name != "p"
        routers[name] = {
            "links": json.dumps([{"ifname": "access", "flags": ["UP", "LOWER_UP"], "mtu": 1500}]),
            "ospf": json.dumps({"10.0.0.1": [{"nbrState": "Full/DR", "ifaceName": "access"}]}) if access else "{}",
            "isis": "p 0 Up 00:00:20" if name in ("pe1", "pe2") else "pe1 0 Up 20\npe2 0 Up 20" if name == "p" else "",
            "bgp": json.dumps({"ipv4Unicast": {"peers": {ip: {"state": "Established"} for ip in addresses}}}),
            "routes": json.dumps({prefix: [{"protocol": "bgp", "selected": True, "installed": True}]
                                  for prefix in ("198.18.1.0/24", "198.18.2.0/24")}),
            "config": "interface access\n ip ospf area 0.0.0.0\n!\n",
            "logs": "", "errors": [],
        }
        if access:
            remote = {"ce1": "198.19.1.2/32", "pe1": "198.19.1.1/32",
                      "pe2": "198.19.2.2/32", "ce2": "198.19.2.1/32"}[name]
            routes = json.loads(routers[name]["routes"])
            routes[remote] = [{"protocol": "ospf", "selected": True, "installed": True}]
            routers[name]["routes"] = json.dumps(routes)
    return {"routers": routers}


def test_healthy_requires_protocols_and_routes():
    assert diagnose(healthy())["cause"] == "healthy"


@pytest.mark.parametrize("cause", ["link-down", "mtu-mismatch", "wrong-ospf-area", "bgp-prefix-filter", "session-flap"])
def test_faults_are_inferred_from_evidence(cause):
    data = healthy()
    pe = data["routers"]["pe1"]
    if cause == "link-down":
        pe["links"] = '[{"ifname":"access","flags":[],"mtu":1500}]'
    elif cause == "mtu-mismatch":
        pe["links"] = '[{"ifname":"access","flags":["UP"],"mtu":1400}]'
        pe["ospf"] = '{"10.0.0.1":[{"nbrState":"ExStart/DR"}]}'
    elif cause == "wrong-ospf-area":
        pe["config"] = "interface access\n ip ospf area 0.0.0.9\n!\n"
        pe["ospf"] = '{}'
    elif cause == "bgp-prefix-filter":
        pe["config"] += "ip prefix-list BLOCK seq 5 deny 198.18.1.0/24\nrouter bgp 65000\n address-family ipv4 unicast\n  neighbor 10.10.1.2 prefix-list BLOCK in\n"
        pe["routes"] = '{}'
    else:
        pe["config"] += "router bgp 65000\n neighbor 10.10.1.2 shutdown\n"
        pe["logs"] = "ADJCHANGE neighbor 10.10.1.2 Down User shut down the session"
    result = diagnose(data)
    assert result["cause"] == cause
    assert result["evidence"] and result["fix"]
    assert cause not in json.dumps(data)  # no injected answer label in the input


@pytest.mark.parametrize("command", ["links", "ospf", "bgp", "routes"])
def test_malformed_output_is_incomplete_not_healthy(command):
    data = healthy()
    data["routers"]["pe1"][command] = "% Unknown command"
    assert diagnose(data)["cause"] == "incomplete-evidence"


def test_empty_snapshot_cannot_pass():
    assert diagnose({"routers": {}})["cause"] == "incomplete-evidence"


def test_missing_installed_customer_route_is_unknown():
    data = healthy()
    data["routers"]["pe2"]["routes"] = '{"198.18.1.0/24":[{"protocol":"bgp","selected":false,"installed":false}]}'
    assert diagnose(data)["cause"] == "unknown"


def test_missing_or_down_neighbor_cannot_pass():
    data = healthy()
    data["routers"]["p"]["isis"] = "pe1 0 Down 0"
    assert diagnose(data)["cause"] == "unknown"


def test_collection_error_cannot_pass():
    data = healthy()
    data["routers"]["ce1"]["errors"] = ["docker exec timed out"]
    assert diagnose(data)["cause"] == "incomplete-evidence"


def test_parsers_handle_frr_nested_neighbors_and_reject_wrong_shapes():
    assert ospf_states('{"1.1.1.1":[{"nbrState":"Full/Backup"}]}') == ["Full/Backup"]
    assert bgp_peers('{"ipv4Unicast":{"peers":{"1.1.1.1":{"state":"Idle"}}}}')["1.1.1.1"]["state"] == "Idle"
    with pytest.raises(ValueError):
        parse_json('[]', dict)


def test_diagnosis_does_not_modify_evidence():
    data = healthy()
    before = copy.deepcopy(data)
    diagnose(data)
    assert data == before


def test_frr_command_specific_json_wrappers():
    assert ospf_states('{"neighbors":{"10.254.0.1":[{"nbrState":"Full/-"}]}}') == ["Full/-"]
    assert bgp_peers('{"routerId":"10.255.0.1","peers":{"10.10.1.2":{"state":"Established"}}}')["10.10.1.2"]["state"] == "Established"


def test_full_ospf_neighbors_without_a_learned_route_are_not_healthy():
    data = healthy()
    routes = json.loads(data["routers"]["ce1"]["routes"])
    del routes["198.19.1.2/32"]
    data["routers"]["ce1"]["routes"] = json.dumps(routes)
    assert diagnose(data)["cause"] == "unknown"
