"""Tests for the principal store."""

import json
import os
import stat

import pytest

from nametag_a2h.principal_store import Principal, PrincipalStore


SIGNING_KEY = "test-api-key-for-hmac"


@pytest.fixture
def store(tmp_path):
    return PrincipalStore(data_dir=tmp_path, signing_key=SIGNING_KEY)


@pytest.fixture
def sample_principal():
    return Principal(
        subject="sub_abc123",
        name="Alice Smith",
        legal_name="Alice Marie Smith",
        enrolled_at="2026-01-01T00:00:00Z",
        enrollment_request_id="req_xyz",
        phone="+15551234567",
    )


class TestPrincipal:
    def test_roundtrip(self, sample_principal):
        import json
        assert Principal.from_json(json.dumps(sample_principal.to_dict())) == sample_principal

    def test_to_dict(self, sample_principal):
        assert sample_principal.to_dict() == {
            "subject": "sub_abc123",
            "name": "Alice Smith",
            "legal_name": "Alice Marie Smith",
            "enrolled_at": "2026-01-01T00:00:00Z",
            "enrollment_request_id": "req_xyz",
            "phone": "+15551234567",
        }


class TestPrincipalStore:
    def test_empty(self, store):
        assert store.get_owner() is None

    def test_set_and_get(self, store, sample_principal):
        store.set_owner(sample_principal)
        assert store.get_owner() == sample_principal

    def test_overwrites(self, store, sample_principal):
        store.set_owner(sample_principal)
        new = Principal("sub_new", "Bob", "", "2026-02-01T00:00:00Z", "req_new", "+15559876543")
        store.set_owner(new)
        assert store.get_owner().subject == "sub_new"

    def test_clear(self, store, sample_principal):
        store.set_owner(sample_principal)
        assert store.clear() is True
        assert store.get_owner() is None

    def test_clear_empty(self, store):
        assert store.clear() is False

    def test_file_is_valid_json(self, store, sample_principal):
        store.set_owner(sample_principal)
        data = json.loads(store.file_path.read_text())
        assert data["subject"] == "sub_abc123"

    def test_corrupted_file_returns_none(self, store):
        store._data_dir.mkdir(parents=True, exist_ok=True)
        store.file_path.write_text("not json")
        store._sig_file.write_text("badsig")
        assert store.get_owner() is None

    def test_creates_nested_data_dir(self, tmp_path):
        store = PrincipalStore(data_dir=tmp_path / "deep" / "nested", signing_key=SIGNING_KEY)
        store.set_owner(Principal("s", "n", "", "e", "r", "p"))
        assert store.get_owner().subject == "s"


class TestHMAC:
    def test_signature_file_created(self, store, sample_principal):
        store.set_owner(sample_principal)
        assert store._sig_file.exists()

    def test_get_owner_returns_none_when_sig_missing(self, store, sample_principal):
        store.set_owner(sample_principal)
        store._sig_file.unlink()
        assert store.get_owner() is None

    def test_get_owner_returns_none_when_sig_wrong(self, store, sample_principal):
        store.set_owner(sample_principal)
        store._sig_file.write_text("0000deadbeef")
        assert store.get_owner() is None

    def test_get_owner_returns_none_when_data_tampered(self, store, sample_principal):
        store.set_owner(sample_principal)
        data = json.loads(store.file_path.read_text())
        data["subject"] = "sub_evil"
        store.file_path.write_text(json.dumps(data, indent=2))
        assert store.get_owner() is None

    def test_clear_removes_both_files(self, store, sample_principal):
        store.set_owner(sample_principal)
        assert store.file_path.exists()
        assert store._sig_file.exists()
        store.clear()
        assert not store.file_path.exists()
        assert not store._sig_file.exists()

    def test_unsigned_principal_returns_none(self, tmp_path, sample_principal):
        store = PrincipalStore(data_dir=tmp_path, signing_key=SIGNING_KEY)
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "principal.json").write_text(
            json.dumps(sample_principal.to_dict(), indent=2)
        )
        assert store.get_owner() is None

    def test_set_owner_raises_without_signing_key(self, tmp_path, sample_principal):
        store = PrincipalStore(data_dir=tmp_path, signing_key=None)
        store._signing_key = None
        with pytest.raises(RuntimeError, match="No signing key"):
            store.set_owner(sample_principal)

    def test_get_owner_returns_none_without_signing_key(self, tmp_path, sample_principal):
        store_with_key = PrincipalStore(data_dir=tmp_path, signing_key=SIGNING_KEY)
        store_with_key.set_owner(sample_principal)
        store_no_key = PrincipalStore(data_dir=tmp_path, signing_key=None)
        store_no_key._signing_key = None
        assert store_no_key.get_owner() is None


class TestFilePermissions:
    def test_principal_file_permissions(self, store, sample_principal):
        store.set_owner(sample_principal)
        mode = store.file_path.stat().st_mode
        assert stat.S_IMODE(mode) == 0o600

    def test_sig_file_permissions(self, store, sample_principal):
        store.set_owner(sample_principal)
        mode = store._sig_file.stat().st_mode
        assert stat.S_IMODE(mode) == 0o600

    def test_directory_permissions(self, store, sample_principal):
        store.set_owner(sample_principal)
        mode = store._data_dir.stat().st_mode
        assert stat.S_IMODE(mode) == 0o700

    def test_signing_key_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NAMETAG_API_KEY", "env-key-123")
        store = PrincipalStore(data_dir=tmp_path)
        assert store._signing_key == "env-key-123"
