"""Сборка MCP-сервера: транспорт stdio (CLI-агенты) или streamable HTTP (Hermes/отладка)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__, log
from .config import Config
from .service import Service
from .tools import register

logger = log.get("server")

INSTRUCTIONS = (
    "Сервер управляет сайтами конструктора TOBIZ: проекты, страницы, блоки и изображения. "
    "Типовой порядок: tobiz_list_projects -> tobiz_list_pages -> tobiz_page_summary -> "
    "tobiz_search_blocks/tobiz_describe_block -> tobiz_add_block/tobiz_update_block -> "
    "tobiz_save_page. Правки живут в черновике и уходят на сайт только при tobiz_save_page."
)


def build(service: Service) -> MCPServer:
    mcp: MCPServer = MCPServer(
        name="tobiz-mcp",
        title="TOBIZ site builder",
        instructions=INSTRUCTIONS,
        version=__version__,
        debug=service.config.log_level == "DEBUG",
        log_level=service.config.log_level,  # type: ignore[arg-type]
    )
    names = register(mcp, service)
    logger.info("инструменты зарегистрированы: %s", ", ".join(names))
    return mcp


def run(service: Service) -> None:
    config = service.config
    mcp = build(service)
    if config.transport == "http":
        _run_http(mcp, config)
        return
    mcp.run(transport="stdio")


def _run_http(mcp: MCPServer, config: Config) -> None:
    import uvicorn
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    app: Any = mcp.streamable_http_app(streamable_http_path=config.http_path)

    if config.http_token:
        expected = f"Bearer {config.http_token}"

        class TokenMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Any, call_next: Any) -> Any:
                if request.headers.get("authorization") != expected:
                    return JSONResponse({"error": "unauthorized"}, status_code=401)
                return await call_next(request)

        app.add_middleware(TokenMiddleware)

    logger.info("HTTP-транспорт на %s:%s%s", config.http_host, config.http_port, config.http_path)
    uvicorn.run(app, host=config.http_host, port=config.http_port, log_level="info")
