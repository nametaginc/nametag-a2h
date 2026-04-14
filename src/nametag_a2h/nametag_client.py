"""Nametag REST API client.

Handles creating verification requests (MARs) and polling for results.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx


# Nametag request status strings (modern API)
STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_SHARED = "shared"
STATUS_REVOKED = "revoked"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"
STATUS_EXPIRED_SCOPES = "expired_scopes"
STATUS_PERSON_DELETED = "person_deleted"
STATUS_REJECTED_UNUSABLE = "rejected_unusable"
STATUS_REJECTED_FRAUD = "rejected_fraud"

TERMINAL_STATUSES = {
    STATUS_SHARED,
    STATUS_REVOKED,
    STATUS_CANCELLED,
    STATUS_EXPIRED,
    STATUS_EXPIRED_SCOPES,
    STATUS_PERSON_DELETED,
    STATUS_REJECTED_UNUSABLE,
    STATUS_REJECTED_FRAUD,
}


@dataclass
class NametagRequest:
    """A Nametag verification request (MAR)."""

    id: str
    status: str
    link: str = ""
    subject: str = ""
    name: str = ""
    legal_name: str = ""
    env: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def is_accepted(self) -> bool:
        return self.status == STATUS_SHARED


class NametagAPIError(Exception):
    """Raised when a Nametag API call fails."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Nametag API error ({status_code}): {message}")


class NametagClient:
    """Client for the Nametag REST API."""

    def __init__(
        self,
        api_key: str,
        env: str,
        base_url: str = "https://nametag.co",
    ):
        self.api_key = api_key
        self.env = env
        self._env_resolved = False
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def _ensure_env_resolved(self) -> None:
        """Resolve env name to env ID.

        Looks up the environment by name via GET /api/envs and replaces
        self.env with the actual ID. Called once before the first API call
        that needs the env ID.
        """
        if self._env_resolved:
            return
        self._env_resolved = True

        resp = await self._http.get("/api/envs")
        if resp.status_code != 200:
            raise NametagAPIError(
                resp.status_code,
                f"Failed to list environments: {resp.text}",
            )

        envs = resp.json()
        if isinstance(envs, dict):
            envs = envs.get("envs", [])

        for env in envs:
            if env.get("name", "").lower() == self.env.lower():
                self.env = env["id"]
                return

        available = [e.get("name", "?") for e in envs]
        raise NametagAPIError(
            404,
            f"Environment '{self.env}' not found. "
            f"Available environments: {', '.join(available)}",
        )

    async def create_request(
        self,
        *,
        phone: str,
        template: str,
        ttl: str = "5m",
        label: str = "",
    ) -> NametagRequest:
        """Create a Nametag verification request (MAR).

        Args:
            phone: Phone number to send verification link to (e.g. "+15551234567").
            template: Nametag template name.
            ttl: Time to live (e.g. "5m", "1h").
            label: Internal tracking label.

        Returns:
            A NametagRequest with id, status, and link.
        """
        await self._ensure_env_resolved()

        body: dict[str, Any] = {
            "env": self.env,
            "template": template,
            "phone": phone,
        }
        if ttl:
            body["ttl"] = ttl
        if label:
            body["label"] = label

        resp = await self._http.post("/api/requests", json=body)
        if resp.status_code not in (200, 201):
            raise NametagAPIError(resp.status_code, resp.text)

        data = resp.json()
        return NametagRequest(
            id=data["id"],
            status=data.get("status", STATUS_PENDING),
            link=data.get("link", ""),
            env=data.get("env", self.env),
        )

    async def get_request(self, request_id: str) -> NametagRequest:
        """Get the current state of a verification request.

        Args:
            request_id: The Nametag request ID.

        Returns:
            A NametagRequest with current status and subject (if completed).
        """
        resp = await self._http.get(f"/api/requests/{request_id}")
        if resp.status_code != 200:
            raise NametagAPIError(resp.status_code, resp.text)

        data = resp.json()
        return NametagRequest(
            id=data["id"],
            status=data.get("status", STATUS_PENDING),
            link=data.get("link", ""),
            subject=data.get("subject", ""),
            name=data.get("subject_text", ""),
            legal_name=data.get("legal_name", ""),  # requires nt:legal_name scope
            env=data.get("env", ""),
        )

    async def poll_until_terminal(
        self,
        request_id: str,
        *,
        timeout: float = 300.0,
        interval: float = 3.0,
    ) -> NametagRequest:
        """Poll a request until it reaches a terminal status.

        Args:
            request_id: The Nametag request ID.
            timeout: Max seconds to wait before giving up.
            interval: Seconds between polls.

        Returns:
            The request in a terminal state.

        Raises:
            TimeoutError: If the request doesn't reach a terminal state in time.
        """
        elapsed = 0.0
        while elapsed < timeout:
            req = await self.get_request(request_id)
            if req.is_terminal:
                return req
            await asyncio.sleep(interval)
            elapsed += interval

        raise TimeoutError(
            f"Nametag request {request_id} did not complete within {timeout}s"
        )
