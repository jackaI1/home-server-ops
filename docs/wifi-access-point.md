# Wi-Fi access point for the desk node

This page has the setup steps and limits for the `wifi_ap` tool. The overview is in the README.

## What the tool writes

One YAML file (see `wifi_ap/examples/example.yaml`) produces four files:

| File | Service | What it does |
| --- | --- | --- |
| `hostapd.conf` | hostapd | Makes the Wi-Fi network: WPA2, the SSID and channel, and `macaddr_acl=1`, so only MAC addresses in the accept file may join. `ap_isolate=1` stops devices from talking to each other. Mode 0600, because it holds the passphrase. |
| `hostapd.accept` | hostapd | One MAC address per line, taken from `devices`. |
| `dnsmasq.conf` | dnsmasq | DHCP on the Wi-Fi interface only, with `dhcp-host` lines that give each device the same address every time. `dhcp-ignore=tag:!known` means an unlisted device gets no address. DNS is off (`port=0`). |
| `nftables.nft` | nftables | The firewall. Devices may send DHCP to the box. Forwarding is closed by default, and the only open path is TCP to `sensor_endpoint` on its port. The home network sees only the box's uplink address, because of masquerading. |

The passphrase comes from `WIFI_AP_PASSPHRASE`, never from the YAML file. It must be 8 to 63 characters.

## Setup on the access point box

Use a dedicated Linux box with a Wi-Fi adapter and a wired port to the home network. The box forwards nothing except the sensor path, so do not run other routing on it.

1. Install `hostapd`, `dnsmasq` and `nftables`.
2. Copy the example and edit it. Set `ap.ap_interface` to the Wi-Fi adapter, `uplink.interface` to the wired port, and the device list to your own MAC addresses.
3. Render into a folder, then copy the files into place:

   ```sh
   python -m wifi_ap check my-ap.yaml
   WIFI_AP_PASSPHRASE='choose-a-long-one' python -m wifi_ap render my-ap.yaml --out ./rendered --state-dir /var/lib/wifi-ap
   python -m wifi_ap verify ./rendered
   sudo install -m 600 rendered/hostapd.conf rendered/hostapd.accept /etc/hostapd/
   sudo install -m 644 rendered/dnsmasq.conf /etc/dnsmasq.d/wifi-ap.conf
   sudo install -m 644 rendered/nftables.nft /etc/nftables.d/wifi-ap.nft
   ```

4. Turn on forwarding and load the firewall: `sudo sysctl -w net.ipv4.ip_forward=1` and `sudo nft -f /etc/nftables.d/wifi-ap.nft`. Make both survive a reboot with your distribution's usual settings.
5. Give the Wi-Fi interface the gateway address from the YAML, then start `hostapd` and `dnsmasq`.

## Limits

- hostapd is not run in the tests. It needs a real Wi-Fi radio, and GitHub's runners have none. The test checks its file with the parser, and checks the other services for real.
- The netns test replaces the Wi-Fi link with a virtual Ethernet pair. Association, WPA handshakes and radio range are not tested.
- The rules assume the box does nothing else. The forward policy is `drop`.
- The sensor endpoint address is fixed in the file. A change means editing the YAML and rendering again.

## Tests

- `python -m pytest -q wifi_ap/tests` checks the validator, the renderer, the parser and the CLI.
- `sudo WIFI_AP_PASSPHRASE=... bash wifi_ap/netns/test_netns.sh` builds three namespaces (`ap`, `home`, `desk`) and runs the DHCP and traffic checks. It needs root, `dnsmasq-base`, `nftables`, `isc-dhcp-client` and `util-linux`. It stops what it started and removes its namespaces when it exits.

The CI workflow is `.github/workflows/wifi-ap.yml`.
