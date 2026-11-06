# link-down

Run `./cases/link-down/reproduce.sh` from the repo root. It deploys a clean lab, checks the baseline, injects the fault, saves evidence, repairs it and removes the lab.

Expected symptoms: pe1/access is down; OSPF and customer BGP disconnect; customer routes disappear.

Fix check: Access UP, OSPF Full, BGP Established, remote routes installed, sourced ping succeeds.

For a manual session, run `./scripts/lab.sh up`, `./scripts/lab.sh inject link-down`, and `./scripts/lab.sh collect`. Repair with `./scripts/lab.sh fix link-down`, verify with `./scripts/lab.sh check`, then run `./scripts/lab.sh down`.
