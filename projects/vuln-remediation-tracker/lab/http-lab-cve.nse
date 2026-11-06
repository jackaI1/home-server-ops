local http = require "http"

description = [[Checks a synthetic loopback lab banner for an Apache version candidate.
This does not exploit or confirm the real vulnerability. It only runs against
127.0.0.1 and requires the X-Lab-Tracker marker emitted by scripts/run_lab.py.]]
author = "Jack Lai"
license = "Same as Nmap--See https://nmap.org/book/man-legal.html"
categories = {"safe", "discovery"}

portrule = function(host, port)
  return host.ip == "127.0.0.1" and port.protocol == "tcp" and port.state == "open"
end

action = function(host, port)
  local response = http.get(host, port, "/")
  if not response or not response.header or response.header["x-lab-tracker"] ~= "synthetic" then
    return "ERROR: synthetic lab marker missing"
  end
  if response.header["server"] == "Apache/2.4.49" then
    return { ["CVE-2021-41773"] = {
      state = "LIKELY VULNERABLE",
      title = "Synthetic Apache banner candidate; version evidence only",
      ids = { CVE = "CVE-2021-41773" }
    }}
  end
  return "NOT VULNERABLE: synthetic banner was changed"
end
