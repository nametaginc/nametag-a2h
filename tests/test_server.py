"""Tests for the MCP server tools."""

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
import httpx
import respx

from nametag_a2h.principal_store import PrincipalStore as FileStore, Principal

ENVS_RESPONSE = {
    "envs": [{"id": "env_abc123", "name": "test_env"}]
}


def mock_envs():
    respx.get("https://nametag.co/api/envs").mock(
        return_value=httpx.Response(200, json=ENVS_RESPONSE)
    )


# All server tests force backend=file via NAMETAG_STORE_BACKEND
SERVER_ENV_BASE = {
    "NAMETAG_API_KEY": "test_key",
    "NAMETAG_ENV": "test_env",
    "NAMETAG_STORE_BACKEND": "file",
}


class TestNametagStatus:
    @pytest.mark.asyncio
    async def test_not_enrolled(self, tmp_path):
        env = {**SERVER_ENV_BASE, "NAMETAG_A2H_DATA_DIR": str(tmp_path)}
        with patch.dict(os.environ, env):
            from nametag_a2h.server import nametag_status

            result = await nametag_status()
        assert "No identity enrolled" in result

    @pytest.mark.asyncio
    async def test_enrolled(self, tmp_path):
        store = FileStore(data_dir=tmp_path, signing_key="test_key")
        store.set_owner(
            Principal(
                subject="sub_test",
                name="Test User",
                legal_name="",
                enrolled_at="2026-01-01T00:00:00Z",
                enrollment_request_id="req_1",
                phone="+15551234567",
            )
        )

        env = {**SERVER_ENV_BASE, "NAMETAG_A2H_DATA_DIR": str(tmp_path)}
        with patch.dict(os.environ, env):
            from nametag_a2h.server import nametag_status

            result = await nametag_status()
        assert "Test User" in result
        assert "+15551234567" in result


class TestNametagAuthorize:
    @respx.mock
    @pytest.mark.asyncio
    async def test_approve(self, tmp_path):
        mock_envs()
        store = FileStore(data_dir=tmp_path, signing_key="test_key")
        store.set_owner(
            Principal(
                subject="sub_owner",
                name="Alice Smith",
                legal_name="Alice Marie Smith",
                enrolled_at="2026-01-01T00:00:00Z",
                enrollment_request_id="req_enroll",
                phone="+15551234567",
            )
        )

        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(
                200,
                json={"id": "req_auth", "status": "pending", "link": "https://nametag.co/v/req_auth"},
            )
        )
        respx.get("https://nametag.co/api/requests/req_auth").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "req_auth",
                    "status": "shared",
                    "subject": "sub_owner",
                    "subject_text": "Alice Smith",
                },
            )
        )

        env = {**SERVER_ENV_BASE, "NAMETAG_A2H_DATA_DIR": str(tmp_path)}
        with patch.dict(os.environ, env):
            from nametag_a2h.server import nametag_authorize

            result = await nametag_authorize("Delete old logs")

        assert "Approved" in result
        assert "APPROVE" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_decline_wrong_person(self, tmp_path):
        mock_envs()
        store = FileStore(data_dir=tmp_path, signing_key="test_key")
        store.set_owner(
            Principal(
                subject="sub_owner",
                name="Alice Smith",
                legal_name="Alice Marie Smith",
                enrolled_at="2026-01-01T00:00:00Z",
                enrollment_request_id="req_enroll",
                phone="+15551234567",
            )
        )

        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(
                200,
                json={"id": "req_auth", "status": "pending", "link": "https://nametag.co/v/req_auth"},
            )
        )
        respx.get("https://nametag.co/api/requests/req_auth").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "req_auth",
                    "status": "shared",
                    "subject": "sub_imposter",
                    "subject_text": "Bob Evil",
                },
            )
        )

        env = {**SERVER_ENV_BASE, "NAMETAG_A2H_DATA_DIR": str(tmp_path)}
        with patch.dict(os.environ, env):
            from nametag_a2h.server import nametag_authorize

            result = await nametag_authorize("Delete old logs")

        assert "Declined" in result
        assert "DECLINE" in result

    @pytest.mark.asyncio
    async def test_not_enrolled(self, tmp_path):
        env = {**SERVER_ENV_BASE, "NAMETAG_A2H_DATA_DIR": str(tmp_path)}
        with patch.dict(os.environ, env):
            from nametag_a2h.server import nametag_authorize

            result = await nametag_authorize("Delete old logs")
        assert "No identity enrolled" in result
