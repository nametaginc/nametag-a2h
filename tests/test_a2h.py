"""Tests for A2H message types."""

from nametag_a2h.a2h import (
    A2HAuthorizeIntent,
    A2HResponse,
    Assurance,
    Channel,
    Decision,
    InteractionState,
    NametagEvidence,
    Render,
    make_approve_response,
    make_authorize_intent,
    make_decline_response,
)


class TestChannel:
    def test_to_dict(self):
        ch = Channel(type="sms", address="tel:+15551234567")
        assert ch.to_dict() == {"type": "sms", "address": "tel:+15551234567"}


class TestAssurance:
    def test_defaults(self):
        a = Assurance()
        assert a.level == "HIGH"
        assert a.required_factors == ["idv.nametag.v1"]

    def test_to_dict(self):
        a = Assurance(level="MEDIUM")
        d = a.to_dict()
        assert d["level"] == "MEDIUM"
        assert "idv.nametag.v1" in d["required_factors"]


class TestNametagEvidence:
    def test_to_dict(self):
        e = NametagEvidence(
            nametag_request_id="req_123",
            subject="sub_abc",
            subject_matches_principal=True,
            verified_name="Alice",
            verification_timestamp="2026-01-01T00:00:00Z",
        )
        d = e.to_dict()
        assert d["factor"] == "idv.nametag.v1"
        assert d["nametag_request_id"] == "req_123"
        assert d["subject"] == "sub_abc"
        assert d["subject_matches_principal"] is True
        assert d["verified_name"] == "Alice"


class TestA2HAuthorizeIntent:
    def test_defaults(self):
        intent = A2HAuthorizeIntent()
        assert intent.a2h_version == "1.0"
        assert intent.type == "AUTHORIZE"
        assert intent.state == InteractionState.PENDING
        assert intent.ttl_sec == 300
        assert intent.interaction_id  # should be a non-empty UUID

    def test_to_dict(self):
        intent = A2HAuthorizeIntent(
            agent_id="agent-1",
            principal_id="sub_abc",
            channel=Channel(type="sms", address="tel:+1555"),
            render=Render(title="Test", body="Test body"),
        )
        d = intent.to_dict()
        assert d["a2h_version"] == "1.0"
        assert d["type"] == "AUTHORIZE"
        assert d["agent_id"] == "agent-1"
        assert d["principal_id"] == "sub_abc"
        assert d["channel"] == {"type": "sms", "address": "tel:+1555"}
        assert d["render"]["title"] == "Test"
        assert d["state"] == "PENDING"


class TestA2HResponse:
    def test_approve_to_dict(self):
        evidence = NametagEvidence(
            nametag_request_id="req_1",
            subject="sub_1",
            subject_matches_principal=True,
            verified_name="Alice",
            verification_timestamp="2026-01-01T00:00:00Z",
        )
        resp = A2HResponse(
            interaction_id="int_1",
            decision=Decision.APPROVE,
            evidence=evidence,
        )
        d = resp.to_dict()
        assert d["decision"] == "APPROVE"
        assert d["evidence"]["subject_matches_principal"] is True
        assert "reason" not in d

    def test_decline_to_dict(self):
        resp = A2HResponse(
            interaction_id="int_1",
            decision=Decision.DECLINE,
            reason="Identity mismatch",
        )
        d = resp.to_dict()
        assert d["decision"] == "DECLINE"
        assert d["reason"] == "Identity mismatch"
        assert "evidence" not in d


class TestHelpers:
    def test_make_authorize_intent(self):
        intent = make_authorize_intent(
            action="Delete backups",
            phone="+15551234567",
            principal_id="sub_abc",
            agent_id="agent-1",
            ttl_sec=120,
        )
        assert intent.type == "AUTHORIZE"
        assert intent.principal_id == "sub_abc"
        assert intent.channel.address == "tel:+15551234567"
        assert "Delete backups" in intent.render.body
        assert intent.ttl_sec == 120

    def test_make_approve_response(self):
        evidence = NametagEvidence(
            nametag_request_id="req_1",
            subject="sub_1",
            subject_matches_principal=True,
            verified_name="Alice",
            verification_timestamp="2026-01-01T00:00:00Z",
        )
        resp = make_approve_response(
            interaction_id="int_1",
            evidence=evidence,
        )
        assert resp.decision == Decision.APPROVE
        assert resp.evidence is evidence

    def test_make_decline_response(self):
        resp = make_decline_response(
            interaction_id="int_1",
            reason="Wrong person",
        )
        assert resp.decision == Decision.DECLINE
        assert resp.reason == "Wrong person"
        assert resp.evidence is None

    def test_make_decline_response_with_evidence(self):
        evidence = NametagEvidence(
            nametag_request_id="req_1",
            subject="sub_wrong",
            subject_matches_principal=False,
            verified_name="Bob",
            verification_timestamp="2026-01-01T00:00:00Z",
        )
        resp = make_decline_response(
            interaction_id="int_1",
            reason="Identity mismatch",
            evidence=evidence,
        )
        assert resp.decision == Decision.DECLINE
        assert resp.evidence is evidence
        assert resp.evidence.subject_matches_principal is False
