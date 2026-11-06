"""Fault recipes; diagnosis deliberately has no dependency on this module."""
CASES = {
    "link-down": {"symptoms": "pe1/access is down; OSPF and customer BGP disconnect; customer routes disappear.",
                  "fix_check": "Access UP, OSPF Full, BGP Established, remote routes installed, sourced ping succeeds."},
    "mtu-mismatch": {"symptoms": "Access MTUs differ; restarted OSPF stalls in ExStart/Exchange while BGP may stay up.",
                     "fix_check": "Both MTUs 1500, OSPF Full, all baseline routes and ping restored."},
    "wrong-ospf-area": {"symptoms": "Access areas differ; OSPF neighbors disappear even though BGP can remain up.",
                        "fix_check": "Both areas 0.0.0.0, OSPF Full, baseline and ping restored."},
    "bgp-prefix-filter": {"symptoms": "BGP stays Established, but 198.18.1.0/24 disappears beyond ce1.",
                          "fix_check": "BLOCK removed, inbound refresh done, prefix installed on all remote routers and ping succeeds."},
    "session-flap": {"symptoms": "Customer BGP goes down during administrative shutdown; logs record the interruption.",
                     "fix_check": "Shutdown removed, BGP Established, customer routes and ping restored. This is one controlled down/up cycle."},
}


def fault_commands(name, repair=False):
    if name not in CASES:
        raise ValueError(f"Unknown fault: {name}")
    def vty(*commands):
        return ("pe1", "vtysh", commands)
    conf = ("configure terminal",)
    if name == "link-down":
        return [("pe1", "ip", ("link", "set", "access", "up" if repair else "down"))]
    if name == "mtu-mismatch":
        return [("pe1", "ip", ("link", "set", "access", "mtu", "1500" if repair else "1400")),
                vty("clear ip ospf process")]
    if name == "wrong-ospf-area":
        return [vty(*conf, "interface access", "no ip ospf area",
                    "ip ospf area " + ("0.0.0.0" if repair else "0.0.0.9"))]
    if name == "bgp-prefix-filter":
        if repair:
            return [vty(*conf, "router bgp 65000", "address-family ipv4 unicast",
                        "no neighbor 10.10.1.2 prefix-list BLOCK in"),
                    vty(*conf, "no ip prefix-list BLOCK"), vty("clear bgp 10.10.1.2 soft in")]
        return [vty(*conf, "ip prefix-list BLOCK seq 5 deny 198.18.1.0/24",
                    "ip prefix-list BLOCK seq 10 permit 0.0.0.0/0 le 32", "router bgp 65000",
                    "address-family ipv4 unicast", "neighbor 10.10.1.2 prefix-list BLOCK in"),
                vty("clear bgp 10.10.1.2 soft in")]
    return [vty(*conf, "router bgp 65000", ("no " if repair else "") + "neighbor 10.10.1.2 shutdown")]
