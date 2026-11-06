from routing_lab.topology import topology, configs


def test_links_are_isolated_and_interface_names_explicit():
    spec = topology()
    assert len(spec["services"]) == 5
    assert len(spec["networks"]) == 4
    assert all(n["internal"] for n in spec["networks"].values())
    for service in spec["services"].values():
        assert not service.get("ports")
        names = [n["interface_name"] for n in service["networks"].values()]
        assert len(names) == len(set(names))
        assert service["restart"] == "no"


def test_provider_ibgp_is_full_mesh_and_customer_prefixes_not_in_igp():
    cfg = configs()
    for name, own in (("pe1", "10.255.0.1"), ("p", "10.255.0.2"), ("pe2", "10.255.0.3")):
        for peer in ("10.255.0.1", "10.255.0.2", "10.255.0.3"):
            assert (f"neighbor {peer} remote-as 65000" in cfg[name]) == (peer != own)
    assert "ip ospf area" not in cfg["p"]
    assert "ip router isis CORE" in cfg["p"]
    assert "network 198.18.1.0/24" in cfg["ce1"]
    assert "redistribute" not in "".join(cfg.values())
