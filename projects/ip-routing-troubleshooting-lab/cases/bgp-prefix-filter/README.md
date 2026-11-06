# bgp-prefix-filter

Run `./cases/bgp-prefix-filter/reproduce.sh` from the repo root. It deploys a clean lab, checks the baseline, injects the fault, saves evidence, repairs it and removes the lab.

Expected symptoms: BGP stays Established, but 198.18.1.0/24 disappears beyond ce1.

Fix check: BLOCK removed, inbound refresh done, prefix installed on all remote routers and ping succeeds.

For a manual session, run `./scripts/lab.sh up`, `./scripts/lab.sh inject bgp-prefix-filter`, and `./scripts/lab.sh collect`. Repair with `./scripts/lab.sh fix bgp-prefix-filter`, verify with `./scripts/lab.sh check`, then run `./scripts/lab.sh down`.
