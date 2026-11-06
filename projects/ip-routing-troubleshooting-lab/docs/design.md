# Lab design and evidence

I chose Compose rather than containerlab so the only host tools are Docker and Python. Compose 2.36 added explicit interface names, which lets my FRR configuration refer to a cable reliably. `routing_lab/topology.py` generates `lab/compose.json` and the five router configurations. Generated router configuration stays out of git and is mounted read-only. The boot script copies it into the container before changing ownership, so a second run can regenerate files as the same ordinary user.

## Address plan

| Link | Left end | Right end | Protocol |
| --- | --- | --- | --- |
| west, 10.10.1.0/29 | ce1/access .2 | pe1/access .3 | OSPF area 0, eBGP |
| core_west, 10.10.2.0/29 | pe1/core1 .2 | p/core1 .3 | IS-IS level 2, optional LDP |
| core_east, 10.10.3.0/29 | p/core2 .2 | pe2/core1 .3 | IS-IS level 2, optional LDP |
| east, 10.10.4.0/29 | pe2/access .2 | ce2/access .3 | OSPF area 0, eBGP |

Provider loopbacks are 10.255.0.1 through .3. Customer router IDs are 10.254.0.1 and .2. Customer service addresses are 198.18.1.1/24 and 198.18.2.1/24 on loopbacks. Only BGP advertises those service networks. I use shortened hello and hold timers to keep repeatable experiments quick, not as production tuning advice.

Each access endpoint also has a passive OSPF probe interface, `ospf0`: ce1 is 198.19.1.1/32, pe1 is 198.19.1.2/32, pe2 is 198.19.2.1/32 and ce2 is 198.19.2.2/32. The peer must learn that /32 through OSPF and forward a sourced ping to it. A separate dummy interface keeps these probes out of BGP and keeps the customer service networks out of OSPF. No static route can mask a failed probe.

Three full-mesh iBGP sessions avoid a route reflector and make the transit router forward plain IP customer traffic. The two provider edges use next-hop-self toward the other provider routers. There are no static customer routes and no redistribution between the interior protocols. The access OSPF links are separate from the IS-IS core so I can inspect failures without running two competing interior protocols on the same cable.

## Diagnosis contract

`collect` captures the live running configuration, `ip -j link`, OSPF JSON, BGP summary JSON, IP route JSON, IS-IS neighbor text, LDP neighbors, MPLS labels and the last 100 log lines per router. Command timeouts and errors are recorded, not silently replaced with healthy defaults. The JSON snapshot can be diagnosed offline without Docker.

The rules compare both access endpoints for link state, MTU (maximum packet size) and OSPF area. They identify a specific installed inbound prefix rule only when the denied route is missing. They identify the controlled BGP interruption only when both shutdown configuration and a down/reset log entry exist. No case name or injection result is passed to the diagnosis function.

A healthy result requires every expected BGP peer Established, both OSPF relationships Full, both core IS-IS relationships Up, selected and installed BGP routes for each remote customer network, and four installed OSPF probe routes. The separate smoke check sends pings in both directions, sourced from the customer service addresses and from the OSPF probes. It checks customer traffic fails for link, filter and session faults; OSPF-only faults can leave BGP customer traffic working.

Multiple simultaneous faults can produce only the first matching likely cause. The rule library is for this topology, not a general network monitoring system. Missing evidence is `incomplete-evidence`; unexplained missing neighbors or routes are `unknown`. A session flap is a controlled administrative down/up cycle, not a claim that the tool can infer every transient event from one capture.

## MPLS and LDP

On a Linux host, `sudo modprobe mpls_router` and `sudo modprobe mpls_iptunnel` make MPLS kernel support available if those modules exist. `lab/boot.sh` detects its namespace's MPLS sysctls, sets a bounded label table and enables label input only on core interfaces. It then starts LDP with the provider loopback as transport address. The three core containers run privileged because Docker otherwise mounts these sysctls read-only. They have separate network namespaces, no host networking and no host system mounts. The sysctl commands change the container namespace, not the host sysctls.

If MPLS is enabled, smoke requires operational LDP neighbors and a nonempty label table. The evidence contains the actual tables. The customer pings verify forwarding; the lab does not measure MPLS throughput, implement a VPN or prove labeled forwarding by packet capture. Unsupported kernels explicitly use the IP-only path. Customer routers do not run LDP.

## Resource ownership

The default project label is `com.docker.compose.project=iproute-lab`. No host port is published. `up` prints exact container IDs, start times and PIDs in the Docker host. `smoke` saves them in `ownership.json`, repairs in `finally`, and runs `down` in an outer `finally`. CI has another always-run cleanup step. `down` verifies that both containers and networks with the project label are gone. Hard machine shutdowns still require `./scripts/lab.sh down` afterwards.

The lab refuses to overwrite a running project's configuration. Each container has a 128 MB memory limit, a process limit and rotating logs. Use a dedicated Docker daemon if fixed subnets overlap another experiment. I do not restart or remove unrelated workers.

## References I used

- [FRR 10.2.1 release and official image](https://frrouting.org/release/10.2.1/)
- [FRR OSPF configuration](https://docs.frrouting.org/en/stable-10.2/ospfd.html)
- [FRR IS-IS configuration](https://docs.frrouting.org/en/stable-10.2/isisd.html)
- [FRR BGP configuration](https://docs.frrouting.org/en/stable-10.2/bgp.html)
- [FRR LDP configuration](https://docs.frrouting.org/en/stable-10.2/ldpd.html)
- [Compose interface names](https://docs.docker.com/reference/compose-file/services/#interface_name)
