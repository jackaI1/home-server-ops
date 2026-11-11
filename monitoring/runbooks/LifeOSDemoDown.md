# LifeOSDemoDown

**What it means:** the public LifeOS demo at https://lifeos.jacklai.ca/ has not answered the blackbox probe for 10 minutes.

**Check first**
1. Open the demo in a browser on your phone (not on the home network) to rule out your own connection.
2. Look at the `Home server` dashboard, panel "LifeOS demo reachable", and "LifeOS response time".
3. If the response time panel shows a timeout rather than an error code, suspect DNS or the tunnel, not the app.

**Fix**
- If the app process is down, restart it with the restart runbook:
  `cd ansible && ansible-playbook -i inventory/hosts.yml runbooks/restart-service.yml -e service_name=lifeos-demo -e health_url=https://lifeos.jacklai.ca/healthz`
- If the server is up but the site is not, restart the tunnel or reverse proxy on the server, then wait one probe interval (30 s).

**Close it:** the alert resolves on its own once the probe succeeds. Write down the cause in the notes if it was not the app.
