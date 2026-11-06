#!/bin/sh
set -eu
# Keep host-owned source files read-only, including across repeated lab runs.
cp /lab-config/frr.conf /etc/frr/frr.conf
cp /lab-config/daemons /etc/frr/daemons
echo 'service integrated-vtysh-config' > /etc/frr/vtysh.conf
if grep -q '^interface ospf0' /etc/frr/frr.conf; then
    ip link add ospf0 type dummy
    ip link set ospf0 up
fi
# The host must load mpls_router and mpls_iptunnel; never change the host here.
echo 'unavailable: kernel MPLS sysctls absent' > /etc/frr/mpls-status
if [ -e /proc/sys/net/mpls/platform_labels ] && grep -q 'router isis CORE' /etc/frr/frr.conf; then
    sysctl -w net.mpls.platform_labels=10000
    rid=$(sed -n 's/^ bgp router-id //p' /etc/frr/frr.conf)
    {
        echo 'mpls ldp'
        echo " router-id $rid"
        echo ' address-family ipv4'
        echo "  discovery transport-address $rid"
        for interface in /sys/class/net/core*; do
            name=${interface##*/}
            sysctl -w "net.mpls.conf.$name.input=1" >&2
            echo "  interface $name"
            echo '  exit'
        done
        echo ' exit-address-family'
        echo '!'
    } >> /etc/frr/frr.conf
    sed -i 's/^ldpd=no/ldpd=yes/' /etc/frr/daemons
    echo enabled > /etc/frr/mpls-status
fi
chown -R frr:frr /etc/frr
exec /sbin/tini -- /usr/lib/frr/docker-start
