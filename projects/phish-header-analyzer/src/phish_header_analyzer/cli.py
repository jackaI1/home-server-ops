"""Command-line entry point; local files only and no silent overwrites."""

import argparse
import sys
from pathlib import Path

from .analyzer import analyze_bytes
from .identity import normalize_domain
from .parser import MAX_BYTES
from .report import render_json, render_markdown


def brand_mapping(value: str) -> tuple[str, str]:
    name, separator, domain = value.partition("=")
    if (
        not separator
        or not name.strip()
        or not domain.strip()
        or "." not in domain
        or any(c in domain for c in "/@ :")
    ):
        raise argparse.ArgumentTypeError('Use --brand "Display Name=expected.domain"')
    try:
        return name.strip(), normalize_domain(domain.strip())
    except UnicodeError as error:
        raise argparse.ArgumentTypeError("Brand domain must be a valid domain name") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Investigate saved email offline with evidence and uncertainty, not a verdict."
    )
    parser.add_argument("email", type=Path, help="Raw .eml file (maximum 10 MiB)")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument(
        "-o", "--output", type=Path, help="Create a new report file; never overwrite"
    )
    parser.add_argument(
        "--trusted-authserv-id",
        action="append",
        default=[],
        metavar="RECEIVER",
        help="Exact receiver ID from a verified export; repeat for more receivers",
    )
    parser.add_argument(
        "--brand",
        action="append",
        type=brand_mapping,
        default=[],
        metavar="NAME=DOMAIN",
        help="Expected exact display name and sender domain",
    )
    args = parser.parse_args(argv)
    try:
        with args.email.open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        report = analyze_bytes(
            raw,
            source=args.email.name,
            trusted_authserv_ids=tuple(args.trusted_authserv_id),
            brands=dict(args.brand),
        )
        output = render_json(report) if args.format == "json" else render_markdown(report)
        if args.output:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(output)
        else:
            sys.stdout.write(output)
    except (OSError, ValueError, RecursionError) as error:
        # Avoid echoing attacker-controlled email content in terminal errors.
        if isinstance(error, ValueError):
            message = str(error)
        elif isinstance(error, RecursionError):
            message = "Email nesting exceeds the parser limit"
        else:
            message = f"{type(error).__name__}: could not read input or create a new output file"
        print(f"phish-header: {message}", file=sys.stderr)
        return 2
    return 0
