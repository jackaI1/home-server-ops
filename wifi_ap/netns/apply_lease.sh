#!/bin/sh
# dhclient calls this after each DHCP event. On a lease it sets the address and default route on the
# interface, and it appends the leased address to $WIFI_AP_BOUND_LOG so the test can see the event.
# shellcheck disable=SC2154  # dhclient sets reason, interface and new_* variables for this script
case "$reason" in
  BOUND|RENEW|REBIND|REBOOT)
    ip -4 addr flush dev "$interface"
    ip -4 addr add "$new_ip_address/24" dev "$interface"
    ip -4 route replace default via "$new_routers" dev "$interface"
    if [ -n "${WIFI_AP_BOUND_LOG:-}" ]; then
      echo "$new_ip_address" >> "$WIFI_AP_BOUND_LOG"
    fi
    ;;
esac
exit 0
