"""Command-line entry point.

    python -m wifi_ap check  config.yaml
    python -m wifi_ap render config.yaml --out DIR --state-dir /var/lib/wifi-ap
    python -m wifi_ap verify DIR
"""

from __future__ import annotations

import argparse
import dataclasses
import sys

from .config import ConfigError, load_config
from .parsers import ParseError, read_and_parse
from .render import RenderError, passphrase_from_env, render_all


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wifi_ap", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="validate the YAML file and print a summary")
    check.add_argument("config")

    render = sub.add_parser("render", help="write hostapd, dnsmasq and nftables files")
    render.add_argument("config")
    render.add_argument("--out", required=True, help="directory to write into")
    render.add_argument("--state-dir", default="/var/lib/wifi-ap", help="where dnsmasq keeps leases")
    render.add_argument("--ap-interface", help="override ap.ap_interface (used by the netns test)")
    render.add_argument("--uplink-interface", help="override uplink.interface (used by the netns test)")
    render.add_argument("--passphrase-env", default="WIFI_AP_PASSPHRASE")

    verify = sub.add_parser("verify", help="parse rendered files back and check them")
    verify.add_argument("directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "verify":
            summary = read_and_parse(args.directory)
            print(f"ok: hostapd keys={len(summary['hostapd'])} dnsmasq options={len(summary['dnsmasq'])} "
                  f"devices={len(summary['accept'])}")
            return 0

        cfg = load_config(args.config)
        if args.command == "check":
            print(f"ok: ssid={cfg.ssid} channel={cfg.channel} subnet={cfg.subnet} devices={len(cfg.devices)}")
            return 0

        if args.ap_interface or args.uplink_interface:
            cfg = dataclasses.replace(
                cfg,
                ap_interface=args.ap_interface or cfg.ap_interface,
                uplink_interface=args.uplink_interface or cfg.uplink_interface,
            )
        passphrase = passphrase_from_env(args.passphrase_env)
        written = render_all(cfg, passphrase, args.out, args.state_dir)
        read_and_parse(args.out)  # never hand out files that do not parse back
        for name, path in written.items():
            print(f"wrote {path}")
        return 0
    except (ConfigError, RenderError, ParseError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
