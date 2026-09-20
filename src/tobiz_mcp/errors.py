"""Каталог ошибок: единый код + текст + подсказка для агента."""

from __future__ import annotations

from typing import Any


class TobizError(Exception):
    """Ошибка с машинным кодом. В ответе MCP превращается в {code, message, hint}."""

    def __init__(self, code: str, message: str, hint: str = "", raw: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.raw = raw

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint:
            data["hint"] = self.hint
        if self.raw is not None:
            data["raw"] = self.raw
        return data


AUTH_FAILED = "AUTH_FAILED"
AUTH_CAPTCHA = "AUTH_CAPTCHA"
AUTH_LOST = "AUTH_LOST"
ACCESS_DENIED = "ACCESS_DENIED"
UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
NOT_FOUND = "NOT_FOUND"
PAGES_PARSE_FAILED = "PAGES_PARSE_FAILED"
UNKNOWN_FIELD = "UNKNOWN_FIELD"
UNKNOWN_TYPE = "UNKNOWN_TYPE"
TEMPLATE_UNAVAILABLE = "TEMPLATE_UNAVAILABLE"
RENDER_FAILED = "RENDER_FAILED"
SAVE_FAILED = "SAVE_FAILED"
NO_CHANGES = "NO_CHANGES"
CONFLICT = "CONFLICT"
PROJECT_NOT_ALLOWED = "PROJECT_NOT_ALLOWED"
READ_ONLY = "READ_ONLY"
UPLOAD_TOO_LARGE = "UPLOAD_TOO_LARGE"
UPLOAD_INVALID = "UPLOAD_INVALID"
UPLOAD_REJECTED = "UPLOAD_REJECTED"
INBOX_NOT_FOUND = "INBOX_NOT_FOUND"
AMBIGUOUS_PROJECT = "AMBIGUOUS_PROJECT"
BAD_ARGUMENT = "BAD_ARGUMENT"
INTERNAL = "INTERNAL"


def auth_failed() -> TobizError:
    return TobizError(
        AUTH_FAILED,
        "Конструктор отклонил вход с указанными логином и паролем",
        "Проверьте TOBIZ_EMAIL и TOBIZ_PASSWORD",
    )


def auth_captcha() -> TobizError:
    return TobizError(
        AUTH_CAPTCHA,
        "Вход требует ручного прохождения капчи",
        "Войдите в браузере, выгрузите cookie (session, email) в /data/session/cookies.json "
        "и перезапустите контейнер — сервис не обходит капчу",
    )


def upstream_unavailable(exc: object) -> TobizError:
    return TobizError(
        UPSTREAM_UNAVAILABLE,
        f"Нет связи с конструктором: {exc}",
        "Повторите позже; при устойчивой ошибке проверьте сеть и TOBIZ_BASE_URL",
    )


def read_only() -> TobizError:
    return TobizError(READ_ONLY, "Сервис запущен в режиме только чтения (TOBIZ_READ_ONLY=1)")
