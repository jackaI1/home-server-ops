# Routing diagnosis

Likely cause: **bgp-prefix-filter**

An inbound BGP rule blocks the first customer's network.

- pe1 applies BLOCK to 10.10.1.2; BLOCK denies 198.18.1.0/24
- 198.18.1.0/24 is absent from pe1's installed BGP routes

Next step: Remove the BLOCK inbound rule, refresh BGP inbound updates and check the route and ping.

This is a rule-based likely cause, not proof that no other fault exists.

Captured from the [real-router CI run](https://github.com/jackaI1/ip-routing-troubleshooting-lab/actions/runs/42172316938).
