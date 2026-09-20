"""Подготовка файла изображения к загрузке: путь в inbox или base64 из аргумента."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..errors import (
    BAD_ARGUMENT,
    INBOX_NOT_FOUND,
    UPLOAD_INVALID,
    UPLOAD_TOO_LARGE,
    TobizError,
)

MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


@dataclass
class PreparedImage:
    file_name: str
    content: bytes
    content_type: str

    @property
    def size(self) -> int:
        return len(self.content)


def _sniff(content: bytes, file_name: str) -> str:
    for magic, mime in MAGIC:
        if content.startswith(magic):
            return mime
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    head = content[:400].lstrip()
    if head.startswith(b"<svg") or head.startswith(b"<?xml"):
        return "image/svg+xml"
    # никаких догадок по расширению: имя файла подделывается тривиально
    return "application/octet-stream"


def prepare(config: Config, path: str | None, content_base64: str | None,
            file_name: str | None = None) -> PreparedImage:
    if bool(path) == bool(content_base64):
        raise TobizError(
            BAD_ARGUMENT,
            "Укажите ровно одно из полей: path или content_base64",
            "path — файл внутри /data/inbox, content_base64 — содержимое изображения",
        )
    if path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = config.inbox_dir / candidate
        try:
            resolved = candidate.resolve()
            root = config.inbox_dir.resolve()
        except OSError as exc:
            raise TobizError(INBOX_NOT_FOUND, f"Не удалось открыть путь: {exc}")
        if root not in resolved.parents and resolved != root:
            raise TobizError(
                INBOX_NOT_FOUND,
                "Файл вне каталога /data/inbox",
                f"Положите файл в {config.inbox_dir} (том смонтирован в контейнер)",
            )
        if not resolved.is_file():
            raise TobizError(INBOX_NOT_FOUND, f"Файл не найден: {path}")
        content = resolved.read_bytes()
        name = file_name or resolved.name
    else:
        try:
            content = base64.b64decode(str(content_base64), validate=True)
        except (binascii.Error, ValueError):
            raise TobizError(BAD_ARGUMENT, "content_base64 не декодируется",
                             "Передайте корректный base64 без переводов строк")
        name = file_name or "upload.png"

    suffix = Path(name).suffix.lower() or ".png"
    if suffix not in ALLOWED_SUFFIXES:
        raise TobizError(
            UPLOAD_INVALID,
            f"Расширение {suffix} не поддерживается",
            f"Разрешены: {', '.join(sorted(ALLOWED_SUFFIXES))}",
        )
    limit = config.max_upload_mb * 1024 * 1024
    if len(content) > limit:
        raise TobizError(
            UPLOAD_TOO_LARGE,
            f"Файл {len(content)} байт больше лимита {config.max_upload_mb} МБ",
            "Увеличьте TOBIZ_MAX_UPLOAD_MB или уменьшите файл",
        )
    if not content:
        raise TobizError(UPLOAD_INVALID, "Пустой файл")
    content_type = _sniff(content, name)
    if content_type == "application/octet-stream":
        raise TobizError(
            UPLOAD_INVALID,
            "Файл не распознан как изображение",
            "Поддерживаются PNG, JPEG, WEBP, GIF, SVG",
        )
    return PreparedImage(file_name=name, content=content, content_type=content_type)
