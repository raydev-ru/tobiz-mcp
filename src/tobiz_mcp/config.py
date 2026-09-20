"""Конфигурация: всё берётся из переменных окружения, значения по умолчанию уже подобраны."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)


def _env(name: str, default: str | None = None, *aliases: str) -> str | None:
    for key in (name, *aliases):
        value = os.environ.get(key)
        if value not in (None, ""):
            return value
    return default


def _flag(name: str, default: bool = False) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = _env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    # доступ
    email: str | None
    password: str | None
    base_url: str = "https://tobiz.net"
    lp_template: str = "https://{project_id}.lp.tobiz.net"
    user_agent: str = DEFAULT_UA

    # сессия и сеть
    session_dir: Path = Path("/data/session")
    session_ttl: int = 3600
    relogin_max: int = 2
    http_timeout: int = 30
    http_connect_timeout: int = 10
    retries: int = 1

    # режимы
    read_only: bool = False
    dry_run: bool = False
    allowed_project_ids: frozenset[str] = field(default_factory=frozenset)
    max_upload_mb: int = 10
    inbox_dir: Path = Path("/data/inbox")
    assets_dir: Path = Path("/data/assets")
    audit_dir: Path = Path("/data/audit")
    asset_ttl: int = 86400

    # рендер
    renderer_dir: Path = Path("/app/renderer")
    node_bin: str = "node"
    render_timeout: int = 60

    # MCP
    transport: str = "stdio"
    http_host: str = "0.0.0.0"
    http_port: int = 8765
    http_path: str = "/mcp"
    http_token: str | None = None
    log_level: str = "INFO"

    @property
    def has_credentials(self) -> bool:
        return bool(self.email and self.password)

    def lp_base(self, project_id: str) -> str:
        return self.lp_template.format(project_id=project_id)

    def editor_url(self, project_id: str, page_id: str) -> str:
        return f"{self.lp_base(project_id)}/?v={page_id}&editor=true"

    def public_url(self, project_id: str, page_id: str | None = None) -> str:
        base = self.lp_base(project_id)
        return f"{base}/?v={page_id}" if page_id else f"{base}/"

    @classmethod
    def from_env(cls) -> "Config":
        allowed = _env("TOBIZ_ALLOWED_PROJECT_IDS", "") or ""
        return cls(
            email=_env("TOBIZ_EMAIL", None, "TOBIZ_LOGIN"),
            password=_env("TOBIZ_PASSWORD"),
            base_url=(_env("TOBIZ_BASE_URL", "https://tobiz.net") or "").rstrip("/"),
            lp_template=_env("TOBIZ_LP_TEMPLATE", "https://{project_id}.lp.tobiz.net")
            or "https://{project_id}.lp.tobiz.net",
            user_agent=_env("TOBIZ_USER_AGENT", DEFAULT_UA) or DEFAULT_UA,
            session_dir=Path(_env("TOBIZ_SESSION_DIR", "/data/session") or "/data/session"),
            session_ttl=_int("TOBIZ_SESSION_TTL", 3600),
            relogin_max=_int("TOBIZ_RELOGIN_MAX", 2),
            http_timeout=_int("TOBIZ_HTTP_TIMEOUT", 30),
            http_connect_timeout=_int("TOBIZ_HTTP_CONNECT_TIMEOUT", 10),
            retries=_int("TOBIZ_RETRIES", 1),
            read_only=_flag("TOBIZ_READ_ONLY"),
            dry_run=_flag("TOBIZ_DRY_RUN"),
            allowed_project_ids=frozenset(p.strip() for p in allowed.split(",") if p.strip()),
            max_upload_mb=_int("TOBIZ_MAX_UPLOAD_MB", 10),
            inbox_dir=Path(_env("TOBIZ_INBOX_DIR", "/data/inbox") or "/data/inbox"),
            assets_dir=Path(_env("TOBIZ_ASSETS_DIR", "/data/assets") or "/data/assets"),
            audit_dir=Path(_env("TOBIZ_AUDIT_DIR", "/data/audit") or "/data/audit"),
            asset_ttl=_int("TOBIZ_ASSET_TTL", 86400),
            renderer_dir=Path(_env("TOBIZ_RENDERER_DIR", "/app/renderer") or "/app/renderer"),
            node_bin=_env("TOBIZ_NODE_BIN", "node") or "node",
            render_timeout=_int("TOBIZ_RENDER_TIMEOUT", 60),
            transport=(_env("MCP_TRANSPORT", "stdio") or "stdio").lower(),
            http_host=_env("MCP_HTTP_HOST", "0.0.0.0") or "0.0.0.0",
            http_port=_int("MCP_HTTP_PORT", 8765),
            http_path=_env("MCP_HTTP_PATH", "/mcp") or "/mcp",
            http_token=_env("MCP_HTTP_TOKEN"),
            log_level=(_env("TOBIZ_LOG_LEVEL", "INFO") or "INFO").upper(),
        )
