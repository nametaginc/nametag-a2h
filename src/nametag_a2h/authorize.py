"""Orchestration for enrollment and authorization flows.

Ties together the Nametag client, principal store, and A2H message types
to implement the core identity-verified approval flow.
"""

from __future__ import annotations

from dataclasses import dataclass

from .a2h import (
    A2HAuthorizeIntent,
    A2HResponse,
    Decision,
    InteractionState,
    NametagEvidence,
    make_approve_response,
    make_authorize_intent,
    make_decline_response,
)
from .nametag_client import (
    STATUS_SHARED,
    STATUS_EXPIRED,
    STATUS_REJECTED_FRAUD,
    STATUS_REJECTED_UNUSABLE,
    NametagClient,
    NametagRequest,
)
from .principal_store import Principal, PrincipalStore


@dataclass
class EnrollmentResult:
    """Result of an enrollment attempt."""

    success: bool
    message: str
    principal: Principal | None = None
    nametag_link: str = ""
    nametag_request_id: str = ""


@dataclass
class AuthorizeResult:
    """Result of an authorization attempt."""

    approved: bool
    message: str
    a2h_response: A2HResponse | None = None
    a2h_intent: A2HAuthorizeIntent | None = None


class A2HNametagAuthorizer:
    """Orchestrates enrollment and identity-verified authorization."""

    def __init__(
        self,
        client: NametagClient,
        store: PrincipalStore,
        template: str = "a2h-verification",
        poll_timeout: float = 300.0,
        poll_interval: float = 3.0,
    ):
        self.client = client
        self.store = store
        self.template = template
        self.poll_timeout = poll_timeout
        self.poll_interval = poll_interval

    async def enroll(self, phone: str) -> EnrollmentResult:
        """Enroll the owner's identity via Nametag verification.

        Creates a Nametag verification request, waits for the owner to
        complete it, and stores their subject ID as the enrolled principal.

        Args:
            phone: Owner's phone number (e.g. "+15551234567").

        Returns:
            EnrollmentResult with success status and message.
        """
        # Create Nametag verification request
        try:
            mar = await self.client.create_request(
                phone=phone,
                template=self.template,
                ttl="5m",
                label="A2H owner enrollment",
            )
        except Exception as e:
            return EnrollmentResult(
                success=False,
                message=f"Failed to create verification request: {e}",
            )

        # Poll until complete
        try:
            result = await self.client.poll_until_terminal(
                mar.id,
                timeout=self.poll_timeout,
                interval=self.poll_interval,
            )
        except TimeoutError:
            return EnrollmentResult(
                success=False,
                message="Verification timed out. Please try again.",
                nametag_link=mar.link,
                nametag_request_id=mar.id,
            )

        if not result.is_accepted:
            return EnrollmentResult(
                success=False,
                message=f"Verification was not completed (status: {result.status}).",
                nametag_request_id=mar.id,
            )

        # Store the principal
        from .a2h import _now_iso

        principal = Principal(
            subject=result.subject,
            name=result.name,
            legal_name=result.legal_name,
            enrolled_at=_now_iso(),
            enrollment_request_id=mar.id,
            phone=phone,
        )

        self.store.set_owner(principal)

        return EnrollmentResult(
            success=True,
            message=f"Enrolled as {result.name}.",
            principal=principal,
            nametag_link=mar.link,
            nametag_request_id=mar.id,
        )

    async def authorize(self, action: str) -> AuthorizeResult:
        """Request identity-verified approval from the enrolled owner.

        Creates a Nametag verification request, waits for someone to
        complete it, then checks that the verified subject matches the
        enrolled owner's subject.

        Args:
            action: Description of the action the agent wants to take.

        Returns:
            AuthorizeResult with approval status and A2H response.
        """
        # Load enrolled owner
        owner = self.store.get_owner()
        if owner is None:
            return AuthorizeResult(
                approved=False,
                message=(
                    "No identity enrolled. The owner must run enrollment "
                    "before actions can be authorized."
                ),
            )

        # Build A2H intent
        intent = make_authorize_intent(
            action=action,
            phone=owner.phone,
            principal_id=owner.subject,
        )
        intent.state = InteractionState.PENDING

        # Create Nametag verification request
        try:
            mar = await self.client.create_request(
                phone=owner.phone,
                template=self.template,
                ttl=f"{intent.ttl_sec}s",
                label=f"A2H approval: {action}",
            )
        except Exception as e:
            return AuthorizeResult(
                approved=False,
                message=f"Failed to create verification request: {e}",
                a2h_intent=intent,
            )

        intent.state = InteractionState.WAITING_INPUT

        # Poll until complete
        try:
            result = await self.client.poll_until_terminal(
                mar.id,
                timeout=self.poll_timeout,
                interval=self.poll_interval,
            )
        except TimeoutError:
            intent.state = InteractionState.EXPIRED
            response = make_decline_response(
                interaction_id=intent.interaction_id,
                reason="Verification timed out — no response from owner.",
            )
            return AuthorizeResult(
                approved=False,
                message="Verification timed out. No response from owner.",
                a2h_response=response,
                a2h_intent=intent,
            )

        # Build evidence
        evidence = NametagEvidence(
            nametag_request_id=mar.id,
            subject=result.subject,
            subject_matches_principal=(result.subject == owner.subject),
            verified_name=result.name,
            verification_timestamp=_now_iso(),
        )

        # Check result
        if result.is_accepted:
            if result.subject == owner.subject:
                # Approved — subject matches enrolled owner
                intent.state = InteractionState.ANSWERED
                response = make_approve_response(
                    interaction_id=intent.interaction_id,
                    evidence=evidence,
                )
                return AuthorizeResult(
                    approved=True,
                    message=f"Approved by {owner.name}.",
                    a2h_response=response,
                    a2h_intent=intent,
                )
            else:
                # Identity mismatch — a different person verified
                intent.state = InteractionState.ANSWERED
                response = make_decline_response(
                    interaction_id=intent.interaction_id,
                    reason=(
                        "Identity mismatch: the person who verified is not "
                        "the enrolled owner."
                    ),
                    evidence=evidence,
                )
                return AuthorizeResult(
                    approved=False,
                    message=(
                        "Declined: the person who verified is not the "
                        "enrolled owner."
                    ),
                    a2h_response=response,
                    a2h_intent=intent,
                )

        # Handle non-accepted terminal statuses
        intent.state = InteractionState.ANSWERED
        reason = _status_to_reason(result.status)
        response = make_decline_response(
            interaction_id=intent.interaction_id,
            reason=reason,
            evidence=evidence if result.subject else None,
        )
        return AuthorizeResult(
            approved=False,
            message=f"Declined: {reason}",
            a2h_response=response,
            a2h_intent=intent,
        )

    def status(self) -> dict:
        """Check enrollment status."""
        owner = self.store.get_owner()
        if owner is None:
            return {"enrolled": False}
        return {
            "enrolled": True,
            "name": owner.name,
            "subject": owner.subject,
            "enrolled_at": owner.enrolled_at,
            "phone": owner.phone,
        }


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _status_to_reason(status: str) -> str:
    reasons = {
        STATUS_EXPIRED: "Verification expired — no response.",
        STATUS_REJECTED_UNUSABLE: "Verification rejected — ID unusable.",
        STATUS_REJECTED_FRAUD: "Verification rejected — suspected fraud.",
    }
    return reasons.get(status, f"Verification failed (status: {status}).")
