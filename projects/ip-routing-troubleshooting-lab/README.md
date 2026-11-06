# ip-routing-troubleshooting-lab

I built a small network that I can deliberately break to learn how the underlying idea works. This is a learning project.

## What I can break

Each folder in [cases/](cases/) has a reproduction script, expected symptoms and a fix check. For example:

```bash
./cases/bgp-prefix-filter/reproduce.sh
cat artifacts/bgp-prefix-filter/bgp-prefix-filter/fault/report.md
```

## Inspect it myself

```bash
./scripts/lab.sh up
./scripts/lab.sh check
./scripts/lab.sh inject wrong-ospf-area
./scripts/lab.sh collect --output artifacts/my-capture
./scripts/lab.sh diagnose artifacts/my-capture/snapshot.json
./scripts/lab.sh fix wrong-ospf-area
./scripts/lab.sh check
./scripts/lab.sh down
```

`up` prints container ownership, Linux host PIDs, start times and the cleanup command. A manual lab stays running until `down`. I use `docker compose -p iproute-lab -f lab/compose.json exec pe1 vtysh` to inspect a router directly. I can set `DOCKER_CONTEXT` for a VM and `ROUTING_LAB_PROJECT` for a separate project name. The four fixed link subnets must be free in that Docker daemon.

## How I arranged the routers

If the Linux kernel exposes MPLS, a forwarding method that uses labels, the core also starts LDP, which exchanges those labels. The smoke test checks operational LDP neighbors and label tables when enabled. Otherwise `mpls-status` records that the kernel lacks support and the same experiment runs with IP routing. I do not claim a VPN or a measured MPLS performance result.

## Tests and limits

There are 5 test source files in this copy. No test pass count is claimed here: I have not re-run the project suite as part of this move. This is a source snapshot, and running it on a new machine may need environment-specific setup.


Project checks run from this directory through the path-filtered hub workflows: (removed workflow).

The relocated workflow did not complete successfully within the migration batch. Local test sources remain available.
