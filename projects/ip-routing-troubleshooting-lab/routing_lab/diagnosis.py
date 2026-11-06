"""Diagnose collected facts, never the name of the requested fault."""
import json
import re

ROUTERS = ("ce1", "pe1", "p", "pe2", "ce2")
PEERS = {"ce1": ("10.10.1.3",), "pe1": ("10.10.1.2", "10.255.0.2", "10.255.0.3"),
         "p": ("10.255.0.1", "10.255.0.3"), "pe2": ("10.10.4.3", "10.255.0.1", "10.255.0.2"),
         "ce2": ("10.10.4.2",)}
OSPF_REMOTE = {"ce1": "198.19.1.2/32", "pe1": "198.19.1.1/32",
               "pe2": "198.19.2.2/32", "ce2": "198.19.2.1/32"}


def parse_json(raw, kind=dict):
    value = json.loads(raw)
    if not isinstance(value, kind):
        raise ValueError(f"Expected {kind.__name__} output")
    return value


def ospf_states(raw):
    data = parse_json(raw)
    data = data.get("neighbors", data)
    return [neighbor["nbrState"] for entries in data.values() if isinstance(entries, list)
            for neighbor in entries if isinstance(neighbor, dict) and "nbrState" in neighbor]


def bgp_peers(raw):
    data = parse_json(raw)
    return data.get("ipv4Unicast", data).get("peers", {})


def interface_area(config):
    block = re.search(r"(?m)^interface access\n((?:[ \t].*\n)*)", config)
    area = re.search(r"ip ospf area (\S+)", block[1]) if block else None
    return area[1] if area else None


def installed_bgp(routes, prefix):
    return any(r.get("protocol") == "bgp" and r.get("selected") and r.get("installed")
               for r in routes.get(prefix, []))


def diagnose(snapshot):
    def result(cause, summary, evidence, fix):
        return {"cause": cause, "summary": summary, "evidence": evidence, "fix": fix}

    try:
        routers = snapshot["routers"]
        links, routes, peers, states = {}, {}, {}, {}
        for name in ROUTERS:
            r = routers[name]
            if r["errors"]:
                raise ValueError(f"{name}: {r['errors']}")
            links[name] = {i["ifname"]: i for i in parse_json(r["links"], list)}
            routes[name] = parse_json(r["routes"])
            peers[name] = bgp_peers(r["bgp"])
            states[name] = ospf_states(r["ospf"])
            for field in ("config", "logs", "isis"):
                if not isinstance(r[field], str):
                    raise ValueError(f"{name}: missing {field}")
        for left, right in (("ce1", "pe1"), ("pe2", "ce2")):
            a, b = links[left]["access"], links[right]["access"]
            for name, interface in ((left, a), (right, b)):
                if "UP" not in interface["flags"]:
                    return result("link-down", f"The customer link on {name} is switched off.",
                                  [f"{name}/access flags: {interface['flags']}"],
                                  f"Bring {name}/access up and wait for OSPF and BGP to reconnect.")
            if a["mtu"] != b["mtu"]:
                return result("mtu-mismatch", "The link ends disagree about the largest packet they accept.",
                              [f"{left}/access MTU {a['mtu']}; {right}/access MTU {b['mtu']}",
                               f"OSPF states: {states[left]} / {states[right]}"],
                              "Set both access interfaces to MTU 1500, restart the OSPF adjacency and check Full.")
            areas = interface_area(routers[left]["config"]), interface_area(routers[right]["config"])
            if None in areas:
                raise ValueError("Missing access OSPF area configuration")
            if areas[0] != areas[1]:
                return result("wrong-ospf-area", "The customer link ends belong to different OSPF areas.",
                              [f"{left}: area {areas[0]}; {right}: area {areas[1]}",
                               f"OSPF states: {states[left]} / {states[right]}"],
                              "Put both access interfaces in area 0.0.0.0 and check the neighbor reaches Full.")
        pe = routers["pe1"]
        if ("neighbor 10.10.1.2 prefix-list BLOCK in" in pe["config"]
                and "ip prefix-list BLOCK seq 5 deny 198.18.1.0/24" in pe["config"]
                and not installed_bgp(routes["pe1"], "198.18.1.0/24")):
            return result("bgp-prefix-filter", "An inbound BGP rule blocks the first customer's network.",
                          ["pe1 applies BLOCK to 10.10.1.2; BLOCK denies 198.18.1.0/24",
                           "198.18.1.0/24 is absent from pe1's installed BGP routes"],
                          "Remove the BLOCK inbound rule, refresh BGP inbound updates and check the route and ping.")
        if ("neighbor 10.10.1.2 shutdown" in pe["config"]
                and re.search(r"(?i)(ADJCHANGE|session|neighbor).*?(Down|reset|shut)", pe["logs"])):
            return result("session-flap", "The customer BGP session was interrupted administratively.",
                          ["pe1 has neighbor 10.10.1.2 shutdown", "BGP logs record a session down/reset event"],
                          "Remove neighbor shutdown, check Established, then verify both customer routes and ping.")
        problems = []
        for name in ROUTERS:
            if any(peers[name].get(ip, {}).get("state") != "Established" for ip in PEERS[name]):
                problems.append(f"{name}: expected BGP peers are not all Established")
            if name != "p" and not any(s.startswith("Full") for s in states[name]):
                problems.append(f"{name}: OSPF is not Full")
            if name in OSPF_REMOTE:
                prefix = OSPF_REMOTE[name]
                if not any(r.get("protocol") == "ospf" and r.get("selected") and r.get("installed")
                           for r in routes[name].get(prefix, [])):
                    problems.append(f"{name}: {prefix} is not installed through OSPF")
            if name in ("pe1", "p", "pe2"):
                expected = 2 if name == "p" else 1
                if len(re.findall(r"\bUp\b", routers[name]["isis"])) < expected:
                    problems.append(f"{name}: missing IS-IS adjacency")
            for prefix, owner in (("198.18.1.0/24", "ce1"), ("198.18.2.0/24", "ce2")):
                if name != owner and not installed_bgp(routes[name], prefix):
                    problems.append(f"{name}: {prefix} is not installed through BGP")
        if problems:
            return result("unknown", "Routing is degraded, but the evidence does not identify one of the known causes.",
                          problems, "Inspect the saved tables, configuration and logs before changing the network.")
        return result("healthy", "All expected routing neighbors and customer routes are present.",
                      ["4 OSPF adjacencies, 4 IS-IS adjacency views and 10 BGP peer views are up",
                       "Both customer networks are installed through BGP wherever remote",
                       "Four remote probe addresses are installed through OSPF"],
                      "No routing repair indicated. Use a sourced ping to check the data path too.")
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        return result("incomplete-evidence", "I cannot diagnose this capture because required evidence is missing or invalid.",
                      [str(exc)], "Collect a fresh snapshot and resolve command errors first.")


def markdown_report(snapshot):
    r = diagnose(snapshot)
    return (f"# Routing diagnosis\n\nLikely cause: **{r['cause']}**\n\n{r['summary']}\n\n"
            + "\n".join(f"- {fact}" for fact in r["evidence"])
            + f"\n\nNext step: {r['fix']}\n\nThis is a rule-based likely cause, not proof that no other fault exists.\n")
