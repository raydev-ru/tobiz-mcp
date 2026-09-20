"""Логи в stderr: stdio-транспорт требует, чтобы stdout был чистым.

Секреты (пароль, значения cookie) маскируются всегда.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

_SECRET_KEYS = {
    "password", "passwd", "pwd", "PHPSESSID", "session", "email", "cookie", "authorization",
}
_SECRET_PATTERNS = [
    re.compile(r"(session=)[0-9a-f]{8,}", re.I),
    re.compile(r"(email=)[^;\s]+", re.I),
    re.compile(r"(password=)[^&\s]+", re.I),
]


def mask(text: str) -> str:
    out = str(text)
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(r"\1***", out)
    return out


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "msg": mask(record.getMessage()),
        }
        for key in ("request_id", "tool", "action", "duration_ms", "status", "project_id",
                    "page_id", "block_id", "code"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = mask(str(value))
        if record.exc_info:
            payload["exc"] = mask(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def setup(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("tobiz_mcp")
    logger.setLevel(getattr(logging, level, logging.INFO))
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    # сторонние логгеры не должны сыпать в stderr построчными «HTTP Request: …»
    for noisy in ("httpx", "httpcore", "mcp", "uvicorn", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logger


def get(component: str) -> logging.LoggerAdapter:
    return logging.LoggerAdapter(logging.getLogger("tobiz_mcp"), {"tool": component})
