"""Точка входа: python -m tobiz_mcp (или консольная команда tobiz-mcp)."""

from __future__ import annotations

import asyncio
import sys

from . import log
from .config import Config
from .server import run
from .service import Service


def main() -> int:
    config = Config.from_env()
    log.setup(config.log_level)
    logger = log.get("main")
    if not config.has_credentials:
        logger.warning("TOBIZ_EMAIL/TOBIZ_PASSWORD не заданы: сервис сможет работать только "
                       "с уже сохранённой сессией в %s", config.session_dir)
    service = Service(config)
    try:
        run(service)
    except KeyboardInterrupt:
        return 130
    finally:
        try:
            asyncio.run(service.aclose())
        except (RuntimeError, asyncio.CancelledError):
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
