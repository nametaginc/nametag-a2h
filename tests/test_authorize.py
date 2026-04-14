"""Tests for the authorization orchestration."""

import pytest
import httpx
import respx

from nametag_a2h.authorize import A2HNametagAuthorizer
from nametag_a2h.nametag_client import NametagClient
from nametag_a2h.principal_store import PrincipalStore as FileStore, Principal

ENVS_RESPONSE = {
    "envs": [{"id": "env_abc123", "name": "test_env"}]
}


def mock_envs():
    respx.get("https://nametag.co/api/envs").mock(
        return_value=httpx.Response(200, json=ENVS_RESPONSE)
    )


@pytest.fixture
def store(tmp_path):
    return FileStore(data_dir=tmp_path, signing_key="test_key")


@pytest.fixture
def client():
    return NametagClient(
        api_key="test_key",
        env="test_env",
        base_url="https://nametag.co",
    )


@pytest.fixture
def authorizer(client, store):
    return A2HNametagAuthorizer(
        client=client,
        store=store,
        template="a2h-verification",
        poll_timeout=5.0,
        poll_interval=0.01,
    )


@pytest.fixture
def enrolled_store(store):
    """A store with an owner already enrolled."""
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
    return store


@pytest.fixture
def enrolled_authorizer(client, enrolled_store):
    return A2HNametagAuthorizer(
        client=client,
        store=enrolled_store,
        template="a2h-verification",
        poll_timeout=5.0,
        poll_interval=0.01,
    )


class TestEnroll:
    @respx.mock
    @pytest.mark.asyncio
    async def test_successful_enrollment(self, authorizer, store):
        mock_envs()
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "req_enroll",
                    "status": "pending",
                    "link": "https://nametag.co/v/req_enroll",
                },
            )
        )
        respx.get("https://nametag.co/api/requests/req_enroll").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "req_enroll",
                    "status": "shared",
                    "subject": "sub_alice",
                    "subject_text": "Alice Smith",
                },
            )
        )

        result = await authorizer.enroll("+15551234567")
        await authorizer.client.close()

        assert result.success is True
        assert "Alice Smith" in result.message
        assert result.principal is not None
        assert result.principal.subject == "sub_alice"
        assert result.principal.name == "Alice Smith"
        assert result.principal.phone == "+15551234567"

        # Verify persisted
        owner = store.get_owner()
        assert owner is not None
        assert owner.subject == "sub_alice"

    @respx.mock
    @pytest.mark.asyncio
    async def test_re_enroll_overwrites(self, enrolled_authorizer, enrolled_store):
        mock_envs()
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "req_new",
                    "status": "pending",
                    "link": "https://nametag.co/v/req_new",
                },
            )
        )
        respx.get("https://nametag.co/api/requests/req_new").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "req_new",
                    "status": "shared",
                    "subject": "sub_new_owner",
                    "subject_text": "Bob Jones",
                },
            )
        )

        result = await enrolled_authorizer.enroll("+15559999999")
        await enrolled_authorizer.client.close()

        assert result.success is True
        assert enrolled_store.get_owner().subject == "sub_new_owner"

    @respx.mock
    @pytest.mark.asyncio
    async def test_enrollment_verification_fails(self, authorizer):
        mock_envs()
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(
                200,
                json={"id": "req_fail", "status": "pending", "link": "https://nametag.co/v/req_fail"},
            )
        )
        respx.get("https://nametag.co/api/requests/req_fail").mock(
            return_value=httpx.Response(
                200,
                json={"id": "req_fail", "status": "rejected_unusable"},
            )
        )

        result = await authorizer.enroll("+15551234567")
        await authorizer.client.close()

        assert result.success is False
        assert "not completed" in result.message

    @respx.mock
    @pytest.mark.asyncio
    async def test_enrollment_api_error(self, authorizer):
        mock_envs()
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        result = await authorizer.enroll("+15551234567")
        await authorizer.client.close()

        assert result.success is False
        assert "Failed to create" in result.message

    @respx.mock
    @pytest.mark.asyncio
    async def test_enrollment_timeout(self, authorizer):
        mock_envs()
        authorizer.poll_timeout = 0.05
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(
                200,
                json={"id": "req_slow", "status": "pending", "link": "https://nametag.co/v/req_slow"},
            )
        )
        respx.get("https://nametag.co/api/requests/req_slow").mock(
            return_value=httpx.Response(
                200, json={"id": "req_slow", "status": "pending"}
            )
        )

        result = await authorizer.enroll("+15551234567")
        await authorizer.client.close()

        assert result.success is False
        assert "timed out" in result.message


class TestAuthorize:
    @respx.mock
    @pytest.mark.asyncio
    async def test_approve_matching_subject(self, enrolled_authorizer):
        mock_envs()
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
                    "subject": "sub_owner",  # matches enrolled
                    "subject_text": "Alice Smith",
                },
            )
        )

        result = await enrolled_authorizer.authorize("Delete backups")
        await enrolled_authorizer.client.close()

        assert result.approved is True
        assert "Approved" in result.message
        assert result.a2h_response is not None
        assert result.a2h_response.decision.value == "APPROVE"
        assert result.a2h_response.evidence.subject_matches_principal is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_decline_wrong_subject(self, enrolled_authorizer):
        mock_envs()
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
                    "subject": "sub_imposter",  # does NOT match enrolled
                    "subject_text": "Bob Evil",
                },
            )
        )

        result = await enrolled_authorizer.authorize("Delete backups")
        await enrolled_authorizer.client.close()

        assert result.approved is False
        assert "not the enrolled owner" in result.message
        assert result.a2h_response is not None
        assert result.a2h_response.decision.value == "DECLINE"
        assert result.a2h_response.evidence.subject_matches_principal is False
        assert result.a2h_response.evidence.subject == "sub_imposter"

    @pytest.mark.asyncio
    async def test_not_enrolled(self, authorizer):
        result = await authorizer.authorize("Delete backups")
        await authorizer.client.close()

        assert result.approved is False
        assert "No identity enrolled" in result.message
        assert result.a2h_response is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_verification_expired(self, enrolled_authorizer):
        mock_envs()
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(
                200,
                json={"id": "req_exp", "status": "pending", "link": "https://nametag.co/v/req_exp"},
            )
        )
        respx.get("https://nametag.co/api/requests/req_exp").mock(
            return_value=httpx.Response(
                200, json={"id": "req_exp", "status": "expired"}
            )
        )

        result = await enrolled_authorizer.authorize("Delete backups")
        await enrolled_authorizer.client.close()

        assert result.approved is False
        assert "expired" in result.message.lower()

    @respx.mock
    @pytest.mark.asyncio
    async def test_verification_rejected_fraud(self, enrolled_authorizer):
        mock_envs()
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(
                200,
                json={"id": "req_fraud", "status": "pending", "link": "https://nametag.co/v/req_fraud"},
            )
        )
        respx.get("https://nametag.co/api/requests/req_fraud").mock(
            return_value=httpx.Response(
                200, json={"id": "req_fraud", "status": "rejected_fraud"}
            )
        )

        result = await enrolled_authorizer.authorize("Delete backups")
        await enrolled_authorizer.client.close()

        assert result.approved is False
        assert "fraud" in result.message.lower()

    @respx.mock
    @pytest.mark.asyncio
    async def test_api_error_on_create(self, enrolled_authorizer):
        mock_envs()
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(500, text="Server error")
        )

        result = await enrolled_authorizer.authorize("Delete backups")
        await enrolled_authorizer.client.close()

        assert result.approved is False
        assert "Failed to create" in result.message

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout_waiting(self, enrolled_authorizer):
        mock_envs()
        enrolled_authorizer.poll_timeout = 0.05
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(
                200,
                json={"id": "req_slow", "status": "pending", "link": "https://nametag.co/v/req_slow"},
            )
        )
        respx.get("https://nametag.co/api/requests/req_slow").mock(
            return_value=httpx.Response(
                200, json={"id": "req_slow", "status": "pending"}
            )
        )

        result = await enrolled_authorizer.authorize("Delete backups")
        await enrolled_authorizer.client.close()

        assert result.approved is False
        assert "timed out" in result.message.lower()

    @respx.mock
    @pytest.mark.asyncio
    async def test_a2h_intent_included(self, enrolled_authorizer):
        mock_envs()
        respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(
                200,
                json={"id": "req_1", "status": "pending", "link": "https://nametag.co/v/req_1"},
            )
        )
        respx.get("https://nametag.co/api/requests/req_1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "req_1",
                    "status": "shared",
                    "subject": "sub_owner",
                    "subject_text": "Alice Smith",
                },
            )
        )

        result = await enrolled_authorizer.authorize("Push to production")
        await enrolled_authorizer.client.close()

        assert result.a2h_intent is not None
        assert result.a2h_intent.type == "AUTHORIZE"
        assert result.a2h_intent.principal_id == "sub_owner"
        assert "Push to production" in result.a2h_intent.render.body

    @respx.mock
    @pytest.mark.asyncio
    async def test_request_label_includes_action(self, enrolled_authorizer):
        mock_envs()
        route = respx.post("https://nametag.co/api/requests").mock(
            return_value=httpx.Response(
                200,
                json={"id": "req_1", "status": "pending", "link": "https://nametag.co/v/req_1"},
            )
        )
        respx.get("https://nametag.co/api/requests/req_1").mock(
            return_value=httpx.Response(
                200,
                json={"id": "req_1", "status": "shared", "subject": "sub_owner", "subject_text": "Alice"},
            )
        )

        await enrolled_authorizer.authorize("Delete all logs")
        await enrolled_authorizer.client.close()

        import json
        body = json.loads(route.calls[0].request.content.decode())
        assert "Delete all logs" in body["label"]


class TestStatus:
    def test_not_enrolled(self, authorizer):
        status = authorizer.status()
        assert status["enrolled"] is False

    def test_enrolled(self, enrolled_authorizer):
        status = enrolled_authorizer.status()
        assert status["enrolled"] is True
        assert status["name"] == "Alice Smith"
        assert status["subject"] == "sub_owner"
        assert status["phone"] == "+15551234567"
