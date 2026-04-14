"""Principal store — enrolled owner identity persisted to disk."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_DATA_DIR = Path.home() / ".nametag-a2h"


@dataclass
class Principal:
    subject: str
    name: str
    legal_name: str
    enrolled_at: str
    enrollment_request_id: str
    phone: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: str) -> Principal:
        return cls(**json.loads(data))


class PrincipalStore:
    def __init__(self, data_dir: Path | None = None, signing_key: str | None = None):
        self._data_dir = data_dir or DEFAULT_DATA_DIR
        self._file = self._data_dir / "principal.json"
        self._sig_file = self._data_dir / "principal.json.sig"
        if signing_key is not None:
            self._signing_key: str | None = signing_key
        else:
            self._signing_key = os.environ.get("NAMETAG_API_KEY")

    @property
    def file_path(self) -> Path:
        return self._file

    def _compute_hmac(self, data: bytes) -> str:
        return hmac.new(
            self._signing_key.encode("utf-8"),
            data,
            hashlib.sha256,
        ).hexdigest()

    def get_owner(self) -> Principal | None:
        if not self._file.exists():
            return None
        if not self._sig_file.exists():
            return None
        if self._signing_key is None:
            return None
        try:
            raw = self._file.read_bytes()
            expected_sig = self._sig_file.read_text(encoding="utf-8").strip()
            if not hmac.compare_digest(self._compute_hmac(raw), expected_sig):
                return None
            return Principal.from_json(raw.decode("utf-8"))
        except (json.JSONDecodeError, TypeError, KeyError, OSError):
            return None

    def set_owner(self, principal: Principal) -> None:
        if self._signing_key is None:
            raise RuntimeError(
                "No signing key available. Set NAMETAG_API_KEY or pass signing_key."
            )
        self._data_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._data_dir, stat.S_IRWXU)
        raw = json.dumps(principal.to_dict(), indent=2).encode("utf-8")
        self._file.write_bytes(raw)
        os.chmod(self._file, stat.S_IRUSR | stat.S_IWUSR)
        self._sig_file.write_text(self._compute_hmac(raw), encoding="utf-8")
        os.chmod(self._sig_file, stat.S_IRUSR | stat.S_IWUSR)

    def clear(self) -> bool:
        removed = False
        if self._sig_file.exists():
            self._sig_file.unlink()
            removed = True
        if self._file.exists():
            self._file.unlink()
            removed = True
        return removed
