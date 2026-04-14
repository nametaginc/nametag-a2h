"""MCP server exposing Nametag A2H tools.

Two tools for agents:
- nametag_authorize: Request identity-verified approval from the enrolled owner.
- nametag_status: Check enrollment status.

Enrollment is intentionally not exposed as a tool — it's a human-initiated action.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .authorize import A2HNametagAuthorizer
from .config import load_approval_required
from .nametag_client import NametagClient
from .principal_store import PrincipalStore


def _build_instructions() -> str:
    items = load_approval_required()
    lines = "\n".join(f"- {item}" for item in items)
    return (
        "This server provides identity-verified human approval for agent actions. "
        "Before taking any of the following actions, ask the user for approval. "
        "If they approve, call nametag_authorize with a description of the action. "
        "Only proceed if identity verification passes.\n\n"
        f"Always require approval before:\n{lines}\n\n"
        "If no owner is enrolled, nametag_authorize will fail — "
        "enrollment must be done by the human outside the agent flow."
    )


server = FastMCP("nametag-a2h", instructions=_build_instructions())


def _get_store():
    data_dir_str = os.environ.get("NAMETAG_A2H_DATA_DIR", "")
    data_dir = Path(data_dir_str) if data_dir_str else None
    return PrincipalStore(data_dir=data_dir)


def _get_authorizer() -> A2HNametagAuthorizer:
    """Build the authorizer from environment variables."""
    api_key = os.environ.get("NAMETAG_API_KEY", "")
    env = os.environ.get("NAMETAG_ENV", "")
    base_url = os.environ.get("NAMETAG_BASE_URL", "https://nametag.co")
    template = os.environ.get("NAMETAG_TEMPLATE", "a2h-verification")

    if not api_key or not env:
        raise RuntimeError(
            "NAMETAG_API_KEY and NAMETAG_ENV environment variables are required."
        )

    client = NametagClient(api_key=api_key, env=env, base_url=base_url)
    store = _get_store()
    return A2HNametagAuthorizer(client=client, store=store, template=template)


@server.tool()
async def nametag_authorize(action: str) -> str:
    """Verify the identity of the user who just approved a sensitive action.

    Call this AFTER the user has given verbal/text approval for an action.
    The owner will receive a verification request on their phone and must
    confirm their identity via Nametag (biometric selfie matched against
    their government ID). The verified identity is compared against the
    enrolled owner — if it matches, the action is confirmed. If a different
    person verifies, or verification fails, the action is denied.

    Flow: ask user → user says yes → call this tool → proceed if verified.

    Args:
        action: A clear description of the action the user approved.
               Example: "Delete all files in /tmp/old-backups"

    Returns:
        A message indicating whether identity verification passed or failed,
        with the A2H protocol response details.
    """
    authorizer = _get_authorizer()
    try:
        result = await authorizer.authorize(action)
    finally:
        await authorizer.client.close()

    parts = [result.message]
    if result.a2h_response:
        parts.append(f"\nA2H Response:\n{json.dumps(result.a2h_response.to_dict(), indent=2)}")
    return "\n".join(parts)


@server.tool()
async def nametag_status() -> str:
    """Check whether an owner identity is enrolled for agent action approvals.

    Returns enrollment details if enrolled, or a message indicating that
    enrollment is needed.
    """
    store = _get_store()
    owner = store.get_owner()

    if owner is None:
        return (
            "No identity enrolled. The owner must run enrollment before "
            "actions can be authorized.\n\n"
            "To enroll, the owner should run:\n"
            "  nametag-a2h enroll <phone-number>"
        )

    return f"Owner enrolled: {owner.name} ({owner.phone})"


def main() -> None:
    """Run the MCP server on stdio transport."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
