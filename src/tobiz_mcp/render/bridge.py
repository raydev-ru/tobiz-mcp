"""Мост к Node-рендереру: шаблоны и хелперы вендора выполняются в Node, не в Python."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from .. import errors, log
from ..config import Config

logger = log.get("render.bridge")


class RenderBridge:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.script = config.renderer_dir / "bridge.js"

    @property
    def available(self) -> bool:
        return self.script.exists() and shutil.which(self.config.node_bin) is not None

    async def _run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.available:
            raise errors.TobizError(
                errors.RENDER_FAILED,
                "Рендерер недоступен: нет node или renderer/bridge.js",
                "Проверьте образ: в нём должны быть Node и каталог /app/renderer",
            )
        request = json.dumps(payload, ensure_ascii=False)
        try:
            process = await asyncio.create_subprocess_exec(
                self.config.node_bin, str(self.script),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise errors.TobizError(errors.RENDER_FAILED, f"Не удалось запустить node: {exc}")
        stdout, stderr = await asyncio.wait_for(
            process.communicate(request.encode("utf-8")),
            timeout=self.config.render_timeout,
        )
        if process.returncode != 0:
            raise errors.TobizError(
                errors.RENDER_FAILED,
                f"Рендерер завершился с кодом {process.returncode}",
                stderr.decode("utf-8", "replace")[-500:],
            )
        try:
            return json.loads(stdout.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise errors.TobizError(
                errors.RENDER_FAILED, f"Рендерер вернул не JSON: {exc}",
                stdout.decode("utf-8", "replace")[:300],
            )

    async def metadata(self, vendor_dir: Path) -> list[dict[str, Any]]:
        """Схемы всех типов блоков из сборки вендора (одноразовый проход Node)."""
        result = await self._run({"op": "meta", "vendor_dir": str(vendor_dir)})
        if not result.get("ok"):
            raise errors.TobizError(errors.RENDER_FAILED,
                                    "Не удалось разобрать библиотеку блоков вендора",
                                    str(result.get("error"))[:300])
        return result.get("types", [])

    async def render(self, vendor_dir: Path, items: list[dict[str, Any]]) -> dict[str, str]:
        """items: [{block_id, type_id, values}] -> {block_id: html}."""
        result = await self._run({"op": "render", "vendor_dir": str(vendor_dir), "items": items})
        if not result.get("ok"):
            failed = result.get("failed") or []
            first = failed[0] if failed else {}
            raise errors.TobizError(
                errors.RENDER_FAILED,
                f"Шаблон блока не отрендерился: {first.get('error', result.get('error'))}",
                f"type_id={first.get('type_id')} block_id={first.get('block_id')}. "
                "Правка на сервер не отправлена: сохранять блок без HTML нельзя "
                "(без готового HTML блок на сайте исчезнет)",
                raw={"failed": failed[:5]},
            )
        return {str(k): str(v) for k, v in result.get("html", {}).items()}
