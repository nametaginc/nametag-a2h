"""Tests for the config loader."""

import json

import pytest

from nametag_a2h.config import DEFAULT_APPROVAL_REQUIRED, load_approval_required


class TestLoadApprovalRequired:
    def test_returns_defaults_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NAMETAG_A2H_DATA_DIR", str(tmp_path))
        assert load_approval_required() == DEFAULT_APPROVAL_REQUIRED

    def test_loads_custom_list(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NAMETAG_A2H_DATA_DIR", str(tmp_path))
        config = {"approval_required": ["Custom action A", "Custom action B"]}
        (tmp_path / "config.json").write_text(json.dumps(config))
        assert load_approval_required() == ["Custom action A", "Custom action B"]

    def test_falls_back_on_missing_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NAMETAG_A2H_DATA_DIR", str(tmp_path))
        (tmp_path / "config.json").write_text(json.dumps({"other_key": "value"}))
        assert load_approval_required() == DEFAULT_APPROVAL_REQUIRED

    def test_falls_back_on_empty_list(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NAMETAG_A2H_DATA_DIR", str(tmp_path))
        (tmp_path / "config.json").write_text(json.dumps({"approval_required": []}))
        assert load_approval_required() == DEFAULT_APPROVAL_REQUIRED

    def test_falls_back_on_corrupt_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NAMETAG_A2H_DATA_DIR", str(tmp_path))
        (tmp_path / "config.json").write_text("not json")
        assert load_approval_required() == DEFAULT_APPROVAL_REQUIRED
