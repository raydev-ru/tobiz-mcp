"""Разбор ответов конструктора: двойное кодирование JSON и текстовые статусы.

Формат (проверено живыми запросами):
  * `{"status":"OK","respons":"<строка JSON>"}` — успех, внутри ещё раз JSON;
  * `{"status":"OK","section_groups":[...]}`, `{"status":"OK","default_values":"<json>"}` — свои поля;
  * `{"status":"OK","html":"<разметка>"}` — панель (`get_projects`);
  * `{"status":"access denied"}` — нет/протухла сессия;
  * `{"status":"ERROR","respons":"текст"}` — ошибка действия (например текст «Сохранил» приходит
    в `respons` у `SaveBlocks` при успехе).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

ACCESS_DENIED = "access denied"


@dataclass
class Envelope:
    status: str
    payload: dict[str, Any]
    raw_text: str

    @property
    def ok(self) -> bool:
        return self.status.upper() == "OK"

    @property
    def denied(self) -> bool:
        return ACCESS_DENIED in (self.raw_text or "").lower() and not self.ok

    @property
    def message(self) -> str:
        """Человекочитаемое сообщение: `respons` у ошибок, иначе пусто."""
        value = self.payload.get("respons")
        if isinstance(value, str) and not value.strip().startswith(("{", "[")):
            return value.strip()
        return ""


def parse(text: str) -> Envelope:
    """Разбирает ответ конструктора. Никогда не бросает исключение."""
    text = text or ""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        lowered = text.lower()
        if "access denied" in lowered:
            return Envelope("access denied", {}, text)
        return Envelope("HTML_OR_TEXT", {}, text)
    if not isinstance(data, dict):
        return Envelope("RAW", {"value": data}, text)
    status = str(data.get("status") or ("OK" if "html" in data else "UNKNOWN"))
    return Envelope(status, data, text)


def json_field(envelope: Envelope, key: str) -> Any:
    """Возвращает поле, которое сервис отдаёт строкой с JSON внутри (respons/data)."""
    value = envelope.payload.get(key)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _decode_json(value: Any, max_depth: int = 3) -> Any:
    """Сервис отдаёт `data` строкой с JSON, а после некоторых сохранений — строкой со строкой.
    Разворачиваем до первого не-строкового результата (устойчиво к обеим формам)."""
    current = value
    for _ in range(max_depth):
        if not isinstance(current, str):
            return current
        text = current.strip()
        if not text.startswith(("{", "[", '"')):
            return current
        try:
            current = json.loads(text)
        except json.JSONDecodeError:
            return current
    return current


def blocks_from(envelope: Envelope) -> list[dict[str, Any]]:
    """Список блоков из ответа `GetBlocks` с развёрнутым полем `data`."""
    blocks = json_field(envelope, "respons")
    if not isinstance(blocks, list):
        return []
    result: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        decoded = _decode_json(block.get("data"))
        block["data_obj"] = decoded if isinstance(decoded, dict) else {}
        result.append(block)
    return result
