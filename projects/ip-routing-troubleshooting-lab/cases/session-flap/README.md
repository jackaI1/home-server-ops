# session-flap

Run `./cases/session-flap/reproduce.sh` from the repo root. It deploys a clean lab, checks the baseline, injects the fault, saves evidence, repairs it and removes the lab.

Expected symptoms: Customer BGP goes down during administrative shutdown; logs record the interruption.

Fix check: Shutdown removed, BGP Established, customer routes and ping restored. This is one controlled down/up cycle.

For a manual session, run `./scripts/lab.sh up`, `./scripts/lab.sh inject session-flap`, and `./scripts/lab.sh collect`. Repair with `./scripts/lab.sh fix session-flap`, verify with `./scripts/lab.sh check`, then run `./scripts/lab.sh down`.
