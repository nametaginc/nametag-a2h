"""Tests for the Nametag API client."""

import json

import pytest
import httpx
import respx

from nametag_a2h.nametag_client import (
    NametagClient,
    NametagAPIError,
    NametagRequest,
    STATUS_PENDING,
    STATUS_SHARED,
    STATUS_EXPIRED,
    TERMINAL_STATUSES,
)

# Standard mock for env resolution — all tests that hit create_request need this
ENVS_RESPONSE = {
    "envs": [
        {"id": "env_abc123", "name": "test_env"},
        {"id": "env_def456", "name": "Production"},
    ]
}


def mock_envs():
    """Register a mock for GET /api/envs."""
    respx.get("https://nametag.co/api/envs").mock(
        return_value=httpx.Response(200, json=ENVS_RESPONSE)
    )


@pytest.fixture
def client():
    return NametagClient(
        api_key="test_key",
        env="test_env",
        base_url="https://nametag.co",
    )


class TestNametagRequest:
    def test_is_terminal(self):
        for status in TERMINAL_STATUSES:
            req = NametagRequest(id="r1", status=status)
            assert req.is_terminal is True

    def test_not_terminal(self):
        req = NametagRequest(id="r1", status=STATUS_PENDING)
        assert req.is_terminal is False

    def test_is_accepted(self):
        req = NametagRequest(id="r1", status=STATUS_SHARED)
        assert req.is_accepted is True

    def test_not_accepted(self):
        req = NametagRequest(id="r1", status=STATUS_EXPIRED)
        assert req.is_accepted is False


class TestEnvResolution:
    @respx.mock
    @pytest.mark.asyncio
    async def test_resolves_name_to_id(self, client):
        mock_envs()
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(200, json={"id": "req_1", "status": "pending"})
        )

        await client.create_request(phone="+1555", template="t", ttl="5m")
        await client.close()

        # env should have been resolved from "test_env" to "env_abc123"
        assert client.env == "env_abc123"

    @respx.mock
    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        client = NametagClient(api_key="k", env="PRODUCTION", base_url="https://nametag.co")
        mock_envs()
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(200, json={"id": "req_1", "status": "pending"})
        )

        await client.create_request(phone="+1555", template="t", ttl="5m")
        await client.close()

        assert client.env == "env_def456"

    @respx.mock
    @pytest.mark.asyncio
    async def test_env_not_found(self):
        client = NametagClient(api_key="k", env="nonexistent", base_url="https://nametag.co")
        mock_envs()

        with pytest.raises(NametagAPIError) as exc_info:
            await client.create_request(phone="+1555", template="t", ttl="5m")
        await client.close()

        assert exc_info.value.status_code == 404
        assert "nonexistent" in str(exc_info.value)
        assert "test_env" in str(exc_info.value)  # lists available envs

    @respx.mock
    @pytest.mark.asyncio
    async def test_env_list_api_error(self):
        client = NametagClient(api_key="k", env="test_env", base_url="https://nametag.co")
        respx.get("https://nametag.co/api/envs").mock(
            return_value=httpx.Response(401, text="Unauthorized")
        )

        with pytest.raises(NametagAPIError) as exc_info:
            await client.create_request(phone="+1555", template="t", ttl="5m")
        await client.close()

        assert exc_info.value.status_code == 401

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolves_only_once(self, client):
        envs_route = respx.get("https://nametag.co/api/envs").mock(
            return_value=httpx.Response(200, json=ENVS_RESPONSE)
        )
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(200, json={"id": "req_1", "status": "pending"})
        )

        await client.create_request(phone="+1555", template="t", ttl="5m")
        await client.create_request(phone="+1555", template="t", ttl="5m")
        await client.close()

        # Should only call /api/envs once
        assert envs_route.call_count == 1


class TestCreateRequest:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client):
        mock_envs()
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "req_123",
                    "status": "pending",
                    "link": "https://nametag.co/v/req_123",
                    "env": "env_abc123",
                },
            )
        )

        result = await client.create_request(
            phone="+15551234567",
            template="a2h-verification",
            ttl="5m",
            label="Test enrollment",
        )
        await client.close()

        assert result.id == "req_123"
        assert result.status == "pending"
        assert result.link == "https://nametag.co/v/req_123"

    @respx.mock
    @pytest.mark.asyncio
    async def test_sends_resolved_env_id(self, client):
        mock_envs()
        route = respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(200, json={"id": "req_1", "status": "pending"})
        )

        await client.create_request(
            phone="+15551234567",
            template="a2h-verification",
            ttl="5m",
            label="Test",
        )
        await client.close()

        request = route.calls[0].request
        data = json.loads(request.content.decode())
        assert data["env"] == "env_abc123"  # resolved ID, not name
        assert data["template"] == "a2h-verification"
        assert data["phone"] == "+15551234567"

    @respx.mock
    @pytest.mark.asyncio
    async def test_sends_auth_header(self, client):
        mock_envs()
        route = respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(200, json={"id": "req_1", "status": "pending"})
        )

        await client.create_request(
            phone="+1555", template="t", ttl="5m"
        )
        await client.close()

        request = route.calls[0].request
        assert request.headers["Authorization"] == "Bearer test_key"

    @respx.mock
    @pytest.mark.asyncio
    async def test_api_error(self, client):
        mock_envs()
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(401, text="Unauthorized")
        )

        with pytest.raises(NametagAPIError) as exc_info:
            await client.create_request(
                phone="+1555", template="t", ttl="5m"
            )
        await client.close()

        assert exc_info.value.status_code == 401


class TestGetRequest:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client):
        respx.get("https://nametag.co/api/requests/req_123").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "req_123",
                    "status": "shared",
                    "subject": "sub_abc",
                    "subject_text": "Alice Smith",
                    "link": "https://nametag.co/v/req_123",
                    "env": "test_env",
                },
            )
        )

        result = await client.get_request("req_123")
        await client.close()

        assert result.id == "req_123"
        assert result.status == "shared"
        assert result.subject == "sub_abc"
        assert result.name == "Alice Smith"

    @respx.mock
    @pytest.mark.asyncio
    async def test_not_found(self, client):
        respx.get("https://nametag.co/api/requests/req_bad").mock(
            return_value=httpx.Response(404, text="Not found")
        )

        with pytest.raises(NametagAPIError) as exc_info:
            await client.get_request("req_bad")
        await client.close()

        assert exc_info.value.status_code == 404


class TestPollUntilTerminal:
    @respx.mock
    @pytest.mark.asyncio
    async def test_immediate_terminal(self, client):
        respx.get("https://nametag.co/api/requests/req_1").mock(
            return_value=httpx.Response(
                200,
                json={"id": "req_1", "status": "shared", "subject": "sub_1", "subject_text": "Alice"},
            )
        )

        result = await client.poll_until_terminal("req_1", interval=0.01)
        await client.close()

        assert result.is_terminal
        assert result.is_accepted

    @respx.mock
    @pytest.mark.asyncio
    async def test_polls_then_completes(self, client):
        call_count = 0

        def side_effect(request):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return httpx.Response(
                    200, json={"id": "req_1", "status": "pending"}
                )
            return httpx.Response(
                200,
                json={"id": "req_1", "status": "shared", "subject": "sub_1", "subject_text": "Alice"},
            )

        respx.get("https://nametag.co/api/requests/req_1").mock(
            side_effect=side_effect
        )

        result = await client.poll_until_terminal("req_1", interval=0.01)
        await client.close()

        assert call_count == 3
        assert result.is_accepted

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout(self, client):
        respx.get("https://nametag.co/api/requests/req_1").mock(
            return_value=httpx.Response(
                200, json={"id": "req_1", "status": "pending"}
            )
        )

        with pytest.raises(TimeoutError):
            await client.poll_until_terminal(
                "req_1", timeout=0.05, interval=0.01
            )
        await client.close()
