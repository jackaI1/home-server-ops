#!/bin/sh
# udhcpc calls this script with the DHCP event as $1 (bound, renew, deconfig, leasefail, nak).
# On a lease it sets the address and default route on $interface, and it appends the leased
# address to $WIFI_AP_BOUND_LOG so the test can see the event. Runs as root inside the desk namespace.
# shellcheck disable=SC2154  # udhcpc sets interface, ip and router for this script
case "$1" in
  bound|renew)
    ip -4 addr flush dev "$interface"
    ip -4 addr add "$ip/24" dev "$interface"
    ip -4 route replace default via "$router" dev "$interface"
    if [ -n "${WIFI_AP_BOUND_LOG:-}" ]; then
      echo "$ip" >> "$WIFI_AP_BOUND_LOG"
    fi
    ;;
esac
exit 0
