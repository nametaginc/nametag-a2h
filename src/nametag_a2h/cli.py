"""CLI for Nametag A2H enrollment.

Human-initiated enrollment — this is intentionally outside the agent's control.
Usage:
    python -m nametag_a2h enroll <phone>
    python -m nametag_a2h status
    python -m nametag_a2h clear
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .authorize import A2HNametagAuthorizer
from .nametag_client import NametagClient
from .principal_store import PrincipalStore


def _get_store():
    data_dir_str = os.environ.get("NAMETAG_A2H_DATA_DIR", "")
    data_dir = Path(data_dir_str) if data_dir_str else None
    return PrincipalStore(data_dir=data_dir)


def _get_config() -> tuple[str, str, str, str]:
    """Read configuration from environment variables."""
    api_key = os.environ.get("NAMETAG_API_KEY", "")
    env = os.environ.get("NAMETAG_ENV", "")
    base_url = os.environ.get("NAMETAG_BASE_URL", "https://nametag.co")
    template = os.environ.get("NAMETAG_TEMPLATE", "a2h-verification")

    if not api_key:
        print("Error: NAMETAG_API_KEY environment variable is required.", file=sys.stderr)
        sys.exit(1)
    if not env:
        print("Error: NAMETAG_ENV environment variable is required.", file=sys.stderr)
        sys.exit(1)

    return api_key, env, base_url, template


async def _enroll(phone: str) -> None:
    api_key, env, base_url, template = _get_config()

    client = NametagClient(api_key=api_key, env=env, base_url=base_url)
    store = _get_store()
    authorizer = A2HNametagAuthorizer(client=client, store=store, template=template)

    print(f"Sending verification link to {phone}...")
    print("Check your phone and scan your government ID.\n")

    try:
        result = await authorizer.enroll(phone)
    finally:
        await client.close()

    if result.success:
        print(f"✓ Enrolled as {result.principal.name}")
        print("\nOwner identity stored. Agents can now request identity-verified approvals.")
    else:
        print(f"✗ Enrollment failed: {result.message}", file=sys.stderr)
        sys.exit(1)


def _status() -> None:
    store = _get_store()
    owner = store.get_owner()

    if owner is None:
        print("No identity enrolled.")
        print("Run: nametag-a2h enroll <phone>")
    else:
        print(f"Enrolled: {owner.name} ({owner.phone})")


def _clear() -> None:
    store = _get_store()

    if store.clear():
        print("✓ Enrolled identity removed.")
    else:
        print("No identity was enrolled.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="nametag-a2h",
        description="Nametag A2H — identity-verified agent approvals",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # enroll
    enroll_parser = subparsers.add_parser(
        "enroll", help="Enroll your identity for agent action approvals"
    )
    enroll_parser.add_argument(
        "phone", help="Your phone number (e.g. +15551234567)"
    )

    # status
    subparsers.add_parser("status", help="Check enrollment status")

    # clear
    subparsers.add_parser("clear", help="Remove enrolled identity")

    args = parser.parse_args()

    try:
        if args.command == "enroll":
            asyncio.run(_enroll(args.phone))
        elif args.command == "status":
            _status()
        elif args.command == "clear":
            _clear()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)


if __name__ == "__main__":
    main()
