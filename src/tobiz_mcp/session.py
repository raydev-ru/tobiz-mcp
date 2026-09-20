"""Хранилище сессии конструктора.

Доступ у TOBIZ держится на паре cookie `session` + `email` (проверено на живом аккаунте),
остальные cookie сохраняем «как есть», но не полагаемся на них.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config

REQUIRED_COOKIES = ("session", "email")


@dataclass
class SessionStore:
    config: Config
    cookies: dict[str, str] = field(default_factory=dict)
    logged_at: float | None = None
    verified_at: float | None = None
    user_id: str | None = None

    @property
    def cookies_path(self) -> Path:
        return self.config.session_dir / "cookies.json"

    @property
    def meta_path(self) -> Path:
        return self.config.session_dir / "meta.json"

    # --- чтение/запись ---

    def load(self) -> bool:
        if not self.cookies_path.exists():
            return False
        try:
            data = json.loads(self.cookies_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        self.cookies = {str(k): str(v) for k, v in (data.get("cookies") or {}).items()}
        self.logged_at = data.get("logged_at")
        self.verified_at = data.get("verified_at")
        self.user_id = data.get("user_id")
        return self.is_configured

    def save(self) -> None:
        self.config.session_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "cookies": self.cookies,
            "logged_at": self.logged_at,
            "verified_at": self.verified_at,
            "user_id": self.user_id,
        }
        self._write_private(self.cookies_path, json.dumps(payload, ensure_ascii=False, indent=2))
        meta = {
            "logged_at": self.logged_at,
            "verified_at": self.verified_at,
            "cookie_names": sorted(self.cookies),
            "user_id": self.user_id,
            "base_url": self.config.base_url,
        }
        self._write_private(self.meta_path, json.dumps(meta, ensure_ascii=False, indent=2))

    def clear(self) -> None:
        self.cookies = {}
        self.logged_at = None
        self.verified_at = None
        for path in (self.cookies_path, self.meta_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _write_private(path: Path, text: str) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)

    # --- состояние ---

    def update_from_client(self, jar: dict[str, str], user_id: str | None = None) -> None:
        self.cookies = {str(k): str(v) for k, v in jar.items()}
        self.logged_at = time.time()
        self.verified_at = None
        if user_id:
            self.user_id = user_id

    def mark_verified(self) -> None:
        self.verified_at = time.time()

    @property
    def is_configured(self) -> bool:
        return all(self.cookies.get(name) for name in REQUIRED_COOKIES)

    @property
    def needs_verify(self) -> bool:
        if not self.is_configured:
            return True
        stamp = self.verified_at or self.logged_at or 0
        return (time.time() - stamp) > self.config.session_ttl

    def cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def describe(self) -> dict[str, object]:
        return {
            "present": self.is_configured,
            "cookie_names": sorted(self.cookies),
            "user_id": self.user_id,
            "logged_at": self.logged_at,
            "verified_at": self.verified_at,
            "age_seconds": int(time.time() - self.logged_at) if self.logged_at else None,
        }
