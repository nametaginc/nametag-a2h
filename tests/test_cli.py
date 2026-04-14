"""Tests for the CLI."""

import subprocess
import sys

import pytest

from nametag_a2h.principal_store import PrincipalStore as FileStore, Principal


class TestCLIStatus:
    def test_status_not_enrolled(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "nametag_a2h", "status"],
            capture_output=True,
            text=True,
            env={
                "NAMETAG_A2H_DATA_DIR": str(tmp_path),
                "NAMETAG_STORE_BACKEND": "file",
                "PATH": "",
            },
        )
        assert "No identity enrolled" in result.stdout

    def test_status_enrolled(self, tmp_path):
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

        result = subprocess.run(
            [sys.executable, "-m", "nametag_a2h", "status"],
            capture_output=True,
            text=True,
            env={
                "NAMETAG_A2H_DATA_DIR": str(tmp_path),
                "NAMETAG_API_KEY": "test_key",
                "NAMETAG_STORE_BACKEND": "file",
                "PATH": "",
            },
        )
        assert "Test User" in result.stdout
        assert "+15551234567" in result.stdout


class TestCLIClear:
    def test_clear_enrolled(self, tmp_path):
        store = FileStore(data_dir=tmp_path, signing_key="test_key")
        store.set_owner(
            Principal(
                subject="sub_test",
                name="Test User",
                legal_name="",
                enrolled_at="2026-01-01T00:00:00Z",
                enrollment_request_id="req_1",
                phone="+1555",
            )
        )

        result = subprocess.run(
            [sys.executable, "-m", "nametag_a2h", "clear"],
            capture_output=True,
            text=True,
            env={
                "NAMETAG_A2H_DATA_DIR": str(tmp_path),
                "NAMETAG_API_KEY": "test_key",
                "NAMETAG_STORE_BACKEND": "file",
                "PATH": "",
            },
        )
        assert "removed" in result.stdout.lower()
        assert store.get_owner() is None

    def test_clear_empty(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "nametag_a2h", "clear"],
            capture_output=True,
            text=True,
            env={
                "NAMETAG_A2H_DATA_DIR": str(tmp_path),
                "NAMETAG_STORE_BACKEND": "file",
                "PATH": "",
            },
        )
        assert "No identity" in result.stdout


class TestCLIEnroll:
    def test_enroll_missing_env_vars(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "nametag_a2h", "enroll", "+15551234567"],
            capture_output=True,
            text=True,
            env={
                "NAMETAG_A2H_DATA_DIR": str(tmp_path),
                "NAMETAG_STORE_BACKEND": "file",
                "PATH": "",
            },
        )
        assert result.returncode != 0
        assert "NAMETAG_API_KEY" in result.stderr

    def test_enroll_missing_phone(self):
        result = subprocess.run(
            [sys.executable, "-m", "nametag_a2h", "enroll"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
