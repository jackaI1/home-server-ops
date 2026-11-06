import pytest

from routing_lab import cli, runtime


def test_smoke_preserves_a_preexisting_manual_lab(monkeypatch, tmp_path):
    removed = []
    monkeypatch.setattr(runtime, "run", lambda *args, **kwargs: "existing-container-id\n")
    monkeypatch.setattr(runtime, "down", lambda: removed.append(True))
    with pytest.raises(RuntimeError, match="already running"):
        cli.smoke(tmp_path, [])
    assert not removed


def test_ldp_checks_actual_uppercase_state_and_expected_neighbor_count():
    assert runtime.ldp_ready("10.255.0.1:0 IPv4 OPERATIONAL", "16 10.255.0.1/32 17", 1)
    assert not runtime.ldp_ready("10.255.0.1:0 IPv4 OPERATIONAL", "16 10.255.0.1/32 17", 2)
    assert not runtime.ldp_ready("10.255.0.1:0 IPv4 OPENSENT", "16 10.255.0.1/32 17", 1)
    assert not runtime.ldp_ready("10.255.0.1:0 IPv4 OPERATIONAL", "No labels", 1)


def test_ospf_fault_must_change_neighbor_state_not_just_configuration():
    from test_diagnosis import healthy
    data = healthy()
    assert not runtime.fault_observed("wrong-ospf-area", data)
    assert not runtime.fault_observed("mtu-mismatch", data)
    data["routers"]["pe1"]["ospf"] = '{}'
    data["routers"]["ce1"]["ospf"] = '{"1.1.1.1":[{"nbrState":"ExStart/DROther"}]}'
    assert runtime.fault_observed("wrong-ospf-area", data)
    assert runtime.fault_observed("mtu-mismatch", data)


def test_prefix_filter_must_leave_bgp_established():
    from test_diagnosis import healthy
    data = healthy()
    assert runtime.fault_observed("bgp-prefix-filter", data)
    data["routers"]["pe1"]["bgp"] = '{}'
    assert not runtime.fault_observed("bgp-prefix-filter", data)


def test_failed_ospf_probe_does_not_count_as_failed_customer_traffic(monkeypatch):
    def network(source, *args):
        if args[-1].startswith("198.19."):
            raise RuntimeError("OSPF test destination is unreachable")
        return "2 packets received"
    monkeypatch.setattr(runtime, "exec_router", network)
    assert not runtime.customer_traffic_fails()
    with pytest.raises(RuntimeError, match="OSPF"):
        runtime.ping()
