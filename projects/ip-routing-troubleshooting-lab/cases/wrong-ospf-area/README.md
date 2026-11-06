# wrong-ospf-area

Run `./cases/wrong-ospf-area/reproduce.sh` from the repo root. It deploys a clean lab, checks the baseline, injects the fault, saves evidence, repairs it and removes the lab.

Expected symptoms: Access areas differ; OSPF neighbors disappear even though BGP can remain up.

Fix check: Both areas 0.0.0.0, OSPF Full, baseline and ping restored.

For a manual session, run `./scripts/lab.sh up`, `./scripts/lab.sh inject wrong-ospf-area`, and `./scripts/lab.sh collect`. Repair with `./scripts/lab.sh fix wrong-ospf-area`, verify with `./scripts/lab.sh check`, then run `./scripts/lab.sh down`.
