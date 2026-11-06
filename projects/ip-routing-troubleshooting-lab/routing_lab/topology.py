"""Single source for Compose links and readable FRR router configurations."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = {"pe1": 1, "p": 2, "pe2": 3}
OSPF_PROBES = {"ce1": "198.19.1.1", "pe1": "198.19.1.2", "pe2": "198.19.2.1", "ce2": "198.19.2.2"}
LINKS = {
    "west": (("ce1", "access", "10.10.1.2"), ("pe1", "access", "10.10.1.3")),
    "core_west": (("pe1", "core1", "10.10.2.2"), ("p", "core1", "10.10.2.3")),
    "core_east": (("p", "core2", "10.10.3.2"), ("pe2", "core1", "10.10.3.3")),
    "east": (("pe2", "access", "10.10.4.2"), ("ce2", "access", "10.10.4.3")),
}


def topology():
    services = {}
    for name in ("ce1", "pe1", "p", "pe2", "ce2"):
        services[name] = {
            "image": "quay.io/frrouting/frr:10.2.1", "hostname": name,
            "cap_add": ["NET_ADMIN", "NET_RAW", "SYS_ADMIN"],
            "sysctls": {"net.ipv4.ip_forward": "1", "net.ipv4.conf.all.rp_filter": "0"},
            "volumes": [f"./generated/{name}:/lab-config:ro", "./boot.sh:/lab-boot.sh:ro"],
            "entrypoint": ["/bin/sh", "/lab-boot.sh"], "restart": "no",
            "privileged": name in CORE,
            "mem_limit": "128m", "pids_limit": 100,
            "logging": {"driver": "json-file", "options": {"max-size": "2m", "max-file": "1"}},
            "networks": {},
        }
    networks = {}
    for index, (link, endpoints) in enumerate(LINKS.items(), 1):
        networks[link] = {"internal": True, "ipam": {"config": [{"subnet": f"10.10.{index}.0/29"}]}}
        for name, interface, ip in endpoints:
            services[name]["networks"][link] = {"ipv4_address": ip, "interface_name": interface}
    return {"services": services, "networks": networks}


def configs():
    output = {}
    for name in ("ce1", "pe1", "p", "pe2", "ce2"):
        rid = f"10.255.0.{CORE[name]}" if name in CORE else f"10.254.0.{1 if name == 'ce1' else 2}"
        lines = [f"hostname {name}", "frr defaults traditional", "log stdout informational",
                 "service integrated-vtysh-config", "interface lo", f" ip address {rid}/32"]
        if name.startswith("ce"):
            customer = 1 if name == "ce1" else 2
            lines.append(f" ip address 198.18.{customer}.1/24")
        else:
            lines += [" ip router isis CORE", " isis passive"]
        lines.append("!")
        if name in OSPF_PROBES:
            lines += ["interface ospf0", f" ip address {OSPF_PROBES[name]}/32", " ip ospf area 0.0.0.0", "!"]
        for endpoints in LINKS.values():
            for router, interface, ip in endpoints:
                if router != name:
                    continue
                lines += [f"interface {interface}", f" ip address {ip}/29"]
                if interface == "access":
                    lines += [" ip ospf area 0.0.0.0", " ip ospf network point-to-point",
                              " ip ospf hello-interval 1", " ip ospf dead-interval 4"]
                else:
                    lines += [" ip router isis CORE", " isis circuit-type level-2-only",
                              " isis network point-to-point", " isis hello-interval 1", " isis hello-multiplier 3"]
                lines.append("!")
        if name != "p":
            lines += ["router ospf", f" ospf router-id {rid}", " passive-interface ospf0",
                      " log-adjacency-changes detail", "!"]
        if name in CORE:
            lines += ["router isis CORE", f" net 49.0001.0000.0000.000{CORE[name]}.00",
                      " is-type level-2-only", " metric-style wide", " log-adjacency-changes", "!"]
        asn = 65000 if name in CORE else 65101 if name == "ce1" else 65102
        lines += [f"router bgp {asn}", f" bgp router-id {rid}", " no bgp ebgp-requires-policy",
                  " no bgp network import-check", " bgp log-neighbor-changes"]
        internal = []
        if name in CORE:
            for other, number in CORE.items():
                if other != name:
                    ip = f"10.255.0.{number}"
                    internal.append(ip)
                    lines += [f" neighbor {ip} remote-as 65000", f" neighbor {ip} update-source lo",
                              f" neighbor {ip} timers 1 3"]
        external = {"ce1": ("10.10.1.3", 65000), "pe1": ("10.10.1.2", 65101),
                    "pe2": ("10.10.4.3", 65102), "ce2": ("10.10.4.2", 65000)}
        if name in external:
            ip, remote = external[name]
            lines += [f" neighbor {ip} remote-as {remote}", f" neighbor {ip} timers 1 3"]
        lines += [" address-family ipv4 unicast"]
        for ip in internal:
            lines.append(f"  neighbor {ip} next-hop-self")
        if name.startswith("ce"):
            lines.append(f"  network 198.18.{1 if name == 'ce1' else 2}.0/24")
        lines += [" exit-address-family", "!", "line vty", "!"]
        output[name] = "\n".join(lines) + "\n"
    return output


def generate():
    directory = ROOT / "lab"
    directory.mkdir(exist_ok=True)
    (directory / "compose.json").write_text(json.dumps(topology(), indent=2) + "\n")
    for name, config in configs().items():
        target = directory / "generated" / name
        target.mkdir(parents=True, exist_ok=True)
        (target / "frr.conf").write_text(config)
        (target / "daemons").write_text("\n".join([
            "zebra=yes", "bgpd=yes", "ospfd=yes", "isisd=yes", "ldpd=no", "vtysh_enable=yes",
            'zebra_options=" -A 127.0.0.1 -s 90000000"', 'bgpd_options=" -A 127.0.0.1"',
            'ospfd_options=" -A 127.0.0.1"', 'isisd_options=" -A 127.0.0.1"',
            'ldpd_options=" -A 127.0.0.1"', ""]))
