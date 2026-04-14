"""A2H (Agent-to-Human) protocol message types.

Implements the subset of the A2H v1.0 spec needed for Nametag identity-verified
agent approvals: AUTHORIZE intents, RESPONSE messages, and the idv.nametag.v1
evidence factor.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class IntentType(str, Enum):
    AUTHORIZE = "AUTHORIZE"
    INFORM = "INFORM"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"


class InteractionState(str, Enum):
    PENDING = "PENDING"
    WAITING_INPUT = "WAITING_INPUT"
    ANSWERED = "ANSWERED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


A2H_VERSION = "1.0"
NAMETAG_FACTOR = "idv.nametag.v1"


def _new_interaction_id() -> str:
    """Generate a UUIDv7-style interaction ID."""
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Channel:
    type: str  # "sms"
    address: str  # "tel:+15551234567"

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "address": self.address}


@dataclass
class Assurance:
    level: str = "HIGH"
    required_factors: list[str] = field(default_factory=lambda: [NAMETAG_FACTOR])

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "required_factors": self.required_factors}


@dataclass
class Render:
    title: str = ""
    body: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "body": self.body}


@dataclass
class NametagEvidence:
    """Evidence from a Nametag identity verification."""

    factor: str = NAMETAG_FACTOR
    nametag_request_id: str = ""
    subject: str = ""
    subject_matches_principal: bool = False
    verified_name: str = ""
    verification_timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class A2HAuthorizeIntent:
    """An A2H AUTHORIZE intent requesting identity-verified approval."""

    interaction_id: str = field(default_factory=_new_interaction_id)
    agent_id: str = ""
    principal_id: str = ""
    channel: Channel = field(default_factory=lambda: Channel(type="sms", address=""))
    render: Render = field(default_factory=Render)
    assurance: Assurance = field(default_factory=Assurance)
    ttl_sec: int = 300
    state: InteractionState = InteractionState.PENDING
    created_at: str = field(default_factory=_now_iso)

    a2h_version: str = A2H_VERSION
    type: str = IntentType.AUTHORIZE

    def to_dict(self) -> dict[str, Any]:
        return {
            "a2h_version": self.a2h_version,
            "interaction_id": self.interaction_id,
            "type": self.type,
            "agent_id": self.agent_id,
            "principal_id": self.principal_id,
            "channel": self.channel.to_dict(),
            "render": self.render.to_dict(),
            "assurance": self.assurance.to_dict(),
            "ttl_sec": self.ttl_sec,
            "state": self.state.value if isinstance(self.state, Enum) else self.state,
            "created_at": self.created_at,
        }


@dataclass
class A2HResponse:
    """An A2H RESPONSE message with a decision and evidence."""

    interaction_id: str = ""
    decision: Decision = Decision.DECLINE
    decided_at: str = field(default_factory=_now_iso)
    evidence: NametagEvidence | None = None
    reason: str | None = None

    a2h_version: str = A2H_VERSION
    type: str = "RESPONSE"

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "a2h_version": self.a2h_version,
            "interaction_id": self.interaction_id,
            "type": self.type,
            "decision": self.decision.value
            if isinstance(self.decision, Enum)
            else self.decision,
            "decided_at": self.decided_at,
        }
        if self.evidence is not None:
            result["evidence"] = self.evidence.to_dict()
        if self.reason is not None:
            result["reason"] = self.reason
        return result


def make_authorize_intent(
    *,
    action: str,
    phone: str,
    principal_id: str = "",
    agent_id: str = "",
    ttl_sec: int = 300,
) -> A2HAuthorizeIntent:
    """Create an AUTHORIZE intent for a given action."""
    return A2HAuthorizeIntent(
        agent_id=agent_id,
        principal_id=principal_id,
        channel=Channel(type="sms", address=f"tel:{phone}"),
        render=Render(
            title="Agent action approval",
            body=f"Approve agent action: {action}",
        ),
        assurance=Assurance(level="HIGH", required_factors=[NAMETAG_FACTOR]),
        ttl_sec=ttl_sec,
    )


def make_approve_response(
    *,
    interaction_id: str,
    evidence: NametagEvidence,
) -> A2HResponse:
    """Create an APPROVE response with Nametag evidence."""
    return A2HResponse(
        interaction_id=interaction_id,
        decision=Decision.APPROVE,
        evidence=evidence,
    )


def make_decline_response(
    *,
    interaction_id: str,
    reason: str,
    evidence: NametagEvidence | None = None,
) -> A2HResponse:
    """Create a DECLINE response with a reason."""
    return A2HResponse(
        interaction_id=interaction_id,
        decision=Decision.DECLINE,
        reason=reason,
        evidence=evidence,
    )
