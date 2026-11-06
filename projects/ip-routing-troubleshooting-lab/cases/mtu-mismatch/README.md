# mtu-mismatch

Run `./cases/mtu-mismatch/reproduce.sh` from the repo root. It deploys a clean lab, checks the baseline, injects the fault, saves evidence, repairs it and removes the lab.

Expected symptoms: Access MTUs differ; restarted OSPF stalls in ExStart/Exchange while BGP may stay up.

Fix check: Both MTUs 1500, OSPF Full, all baseline routes and ping restored.

For a manual session, run `./scripts/lab.sh up`, `./scripts/lab.sh inject mtu-mismatch`, and `./scripts/lab.sh collect`. Repair with `./scripts/lab.sh fix mtu-mismatch`, verify with `./scripts/lab.sh check`, then run `./scripts/lab.sh down`.
