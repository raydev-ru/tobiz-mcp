"""Проверки без MCP: healthcheck контейнера и приёмка.

  python -m tobiz_mcp.selftest --health          # состояние сессии (для docker healthcheck)
  python -m tobiz_mcp.selftest --login           # логин + список проектов
  python -m tobiz_mcp.selftest --catalog <pid>   # сводка по библиотеке блоков проекта
  python -m tobiz_mcp.selftest --render-check <pid>  # рендер блоков страницы против вёрстки
  python -m tobiz_mcp.selftest --page <page_id> [--project <pid>]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from . import log
from .config import Config
from .service import Service


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


async def cmd_health(service: Service) -> int:
    health = await service.health()
    _print(health)
    return 0 if health["session"]["present"] or not service.config.has_credentials else 1


async def cmd_login(service: Service) -> int:
    session = await service.login(force=True)
    projects = await service.projects(refresh=True)
    _print({"session": session, "projects": [p.to_dict() for p in projects]})
    return 0


async def cmd_catalog(service: Service, project_id: str | None) -> int:
    project = await service.project(project_id)
    types = await service.block_types(project.project_id)
    with_template = sum(1 for t in types.values() if t.has_template)
    _print({
        "project_id": project.project_id,
        "types": len(types),
        "with_template": with_template,
        "in_catalog": sum(1 for t in types.values() if t.position is not None),
        "sample": [t.to_public() for t in list(types.values())[:5]],
    })
    return 0


async def cmd_render_check(service: Service, project_id: str | None, page_id: str) -> int:
    project_id, page = await service.resolve_page(project_id, page_id)
    draft = await service.draft(project_id, page_id)
    types = await service.block_types(project_id)
    items = []
    for block_id in draft.order:
        block = draft.blocks[block_id]
        block_type = types.get(block.type_id)
        server_defaults = {}
        if block_type is not None:
            try:
                server_defaults = await service.catalog.default_values(project_id, block_type)
            except Exception:  # noqa: BLE001
                server_defaults = {}
        base = block_type.values if block_type else {}
        items.append({"block_id": block_id, "type_id": block.type_id,
                      "values": {**base, **server_defaults, **block.values}})
    project_dir = service.catalog.project_dir(project_id) / "bundles"
    result = await service.bridge._run({"op": "render", "vendor_dir": str(project_dir),
                                        "items": items})
    report: dict[str, Any] = {
        "page_id": page.page_id,
        "blocks": len(items),
        "rendered": len(result.get("html", {})),
        "failed": result.get("failed", []),
    }
    html = await service.client.fetch_text(service.config.public_url(project_id, page_id))
    report["public_bytes"] = len(html)
    report["blocks_in_public"] = {
        block_id: f'id="b_{block_id}"' in html for block_id in draft.order}
    _print(report)
    return 0 if not report["failed"] else 1


async def cmd_page(service: Service, project_id: str | None, page_id: str) -> int:
    project_id, page = await service.resolve_page(project_id, page_id)
    draft = await service.draft(project_id, page_id)
    _print({"page": page.to_dict(service.config.lp_template, project_id),
            "blocks": [draft.blocks[b].to_dict() for b in draft.order]})
    return 0


async def _run(args: argparse.Namespace) -> int:
    config = Config.from_env()
    log.setup(config.log_level)
    service = Service(config)
    try:
        if args.health:
            return await cmd_health(service)
        if args.login:
            return await cmd_login(service)
        if args.catalog:
            return await cmd_catalog(service, args.project)
        if args.render_check:
            return await cmd_render_check(service, args.project, args.render_check)
        if args.page:
            return await cmd_page(service, args.project, args.page)
        _print({"usage": __doc__})
        return 2
    finally:
        await service.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(prog="tobiz-mcp-selftest", description="Проверки tobiz-mcp")
    parser.add_argument("--health", action="store_true", help="состояние сессии")
    parser.add_argument("--login", action="store_true", help="логин и список проектов")
    parser.add_argument("--catalog", action="store_true", help="сводка по библиотеке блоков")
    parser.add_argument("--render-check", metavar="PAGE_ID", help="рендер блоков страницы")
    parser.add_argument("--page", metavar="PAGE_ID", help="состав страницы")
    parser.add_argument("--project", metavar="PROJECT_ID", default=None, help="project_id")
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
