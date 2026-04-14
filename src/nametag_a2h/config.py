"""Configuration loader for nametag-a2h.

Reads config from {data_dir}/config.json. Falls back to built-in defaults
if the file doesn't exist or omits a setting.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .principal_store import DEFAULT_DATA_DIR

DEFAULT_APPROVAL_REQUIRED = [
    "Deleting or overwriting files or directories",
    "Pushing to a remote git repository",
    "Running scripts downloaded from the internet",
    "Modifying CI/CD pipelines or deployment configuration",
    "Database mutations (DROP, DELETE, TRUNCATE, ALTER)",
    "Sending emails, messages, or notifications to external recipients",
    "Creating or modifying cloud infrastructure",
    "Any action the user describes as dangerous, risky, or destructive",
]


def _data_dir() -> Path:
    val = os.environ.get("NAMETAG_A2H_DATA_DIR", "")
    return Path(val) if val else DEFAULT_DATA_DIR


def load_approval_required() -> list[str]:
    """Return the list of action categories that require approval.

    Reads from {data_dir}/config.json if present. Falls back to defaults.
    """
    config_file = _data_dir() / "config.json"
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            items = data.get("approval_required")
            if isinstance(items, list) and items:
                return items
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_APPROVAL_REQUIRED
