"""Библиотека блоков: скачивание и кэш публичных ресурсов вендора + серверные дефолты.

Ассеты принадлежат конкретному проекту (URL содержит lp-домен), поэтому кэш — подкаталог на
project_id: риск перепутать сборки дороже 2 МБ диска - иначе легко перепутать сборки блоков разных сайтов.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import errors, log
from ..config import Config
from . import endpoints as ep
from .client import TobizClient

logger = log.get("tobiz.catalog")


@dataclass
class BlockType:
    type_id: str
    values: dict[str, Any]
    settings: list[dict[str, Any]]
    vars: list[dict[str, Any]]
    has_template: bool
    title: str = ""
    description: str = ""
    category_id: str = ""
    position: int | None = None

    def to_public(self) -> dict[str, Any]:
        return {
            "type_id": self.type_id,
            "title": self.title,
            "description": self.description,
            "category_id": self.category_id,
            "has_template": self.has_template,
        }


class Catalog:
    def __init__(self, config: Config, client: TobizClient, bridge: Any) -> None:
        self.config = config
        self.client = client
        self.bridge = bridge

    # --- пути ---

    def project_dir(self, project_id: str) -> Path:
        return self.config.assets_dir / str(project_id)

    def _index_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "index.json"

    def _read_json(self, path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    # --- скачивание ассетов ---

    async def ensure_assets(self, project_id: str, force: bool = False) -> dict[str, Any]:
        index = self._read_json(self._index_path(project_id)) or {}
        fetched_at = float(index.get("fetched_at") or 0)
        if not force and index and (time.time() - fetched_at) < self.config.asset_ttl:
            return index

        lp_base = self.config.lp_base(project_id)
        target = self.project_dir(project_id) / "bundles"
        target.mkdir(parents=True, exist_ok=True)

        files: dict[str, Any] = {}
        for path in ep.LP_VENDOR_BUNDLES:
            name = Path(path).name
            try:
                content = await self.client.fetch_bytes(f"{lp_base}{path}")
            except errors.TobizError as exc:
                if name in {"editor.min.js", "blocks2.js", "underscore-min.js"}:
                    raise
                logger.warning("ресурс недоступен: %s (%s)", path, exc.code)
                continue
            (target / name).write_bytes(content)
            files[name] = {
                "name": name,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }

        for path, name in ((ep.LP_CATALOG, "sections.json"),
                           (ep.LP_STYLE_PRESETS, "stylesFontsPresets.json")):
            try:
                content = await self.client.fetch_bytes(f"{lp_base}{path}")
            except errors.TobizError as exc:
                logger.warning("ресурс недоступен: %s (%s)", path, exc.code)
                continue
            (target / name).write_bytes(content)
            files[name] = {"name": name, "bytes": len(content),
                           "sha256": hashlib.sha256(content).hexdigest()}

        index = {
            "project_id": str(project_id),
            "fetched_at": time.time(),
            "lp_base": lp_base,
            "files": files,
        }
        self._write_json(self._index_path(project_id), index)
        # метаданные типов придётся пересобрать: сборка изменилась
        for stale in ("types.json", "defaults.json"):
            try:
                (target / stale).unlink()
            except FileNotFoundError:
                pass
        logger.info("ассеты проекта получены", extra={"project_id": project_id})
        return index

    # --- каталог и типы ---

    async def catalog(self, project_id: str) -> dict[str, Any]:
        await self.ensure_assets(project_id)
        path = self.project_dir(project_id) / "bundles" / "sections.json"
        data = self._read_json(path)
        if not isinstance(data, dict) or "sections" not in data:
            raise errors.TobizError(
                errors.UPSTREAM_UNAVAILABLE,
                "Каталог блоков (sections.json) недоступен",
                "Повторите вызов с обновлением ассетов: tobiz_refresh_assets",
            )
        return data

    def _catalog_index(self, catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for section in catalog.get("sections", []):
            for item in section.get("blocks", []):
                index.setdefault(str(item["id"]), {
                    "type_id": str(item["id"]),
                    "position": item.get("position"),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "category_id": str(section.get("category_id") or ""),
                    "category_name": section.get("name", ""),
                })
        return index

    async def types(self, project_id: str, force: bool = False) -> dict[str, BlockType]:
        await self.ensure_assets(project_id)
        project_path = self.project_dir(project_id) / "bundles"
        types_path = project_path / "types.json"
        meta = None if force else self._read_json(types_path)
        if meta is None:
            meta = await self.bridge.metadata(project_path)
            self._write_json(types_path, meta)
        catalog_index = self._catalog_index(await self.catalog(project_id))
        result: dict[str, BlockType] = {}
        for item in meta:
            type_id = str(item["type_id"])
            catalog_entry = catalog_index.get(type_id, {})
            result[type_id] = BlockType(
                type_id=type_id,
                values=item.get("values") or {},
                settings=item.get("settings") or [],
                vars=item.get("vars") or [],
                has_template=bool(item.get("has_template")),
                title=catalog_entry.get("title", ""),
                description=catalog_entry.get("description", ""),
                category_id=catalog_entry.get("category_id", ""),
                position=catalog_entry.get("position"),
            )
        return result

    async def default_values(self, project_id: str, block_type: BlockType) -> dict[str, Any]:
        """Серверные дефолты типа (fetchSectionDefaultValues) — то, что подставляет редактор."""
        path = self.project_dir(project_id) / "bundles" / "defaults.json"
        cache = self._read_json(path) or {}
        if block_type.type_id in cache:
            value = cache[block_type.type_id]
            return value if isinstance(value, dict) else {}
        if block_type.position is None:
            return dict(block_type.values)
        envelope = await self.client.editor_ajax(
            ep.ACT_DEFAULT_VALUES, self.config.lp_base(project_id), "",
            type_id=block_type.type_id, position=block_type.position,
        )
        values: dict[str, Any] = {}
        raw = envelope.payload.get("default_values")
        if isinstance(raw, str) and raw.strip().startswith("{"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    values = parsed
            except json.JSONDecodeError:
                values = {}
        cache[block_type.type_id] = values
        self._write_json(path, cache)
        return values or dict(block_type.values)

    def search(self, types: dict[str, BlockType], query: str = "", category_id: str = "",
               type_id: str = "", limit: int = 20, offset: int = 0) -> tuple[int, list[BlockType]]:
        needle = (query or "").strip().lower()
        matched: list[BlockType] = []
        for block_type in types.values():
            if category_id and block_type.category_id != str(category_id):
                continue
            if type_id and block_type.type_id != str(type_id):
                continue
            if needle:
                haystack = f"{block_type.type_id} {block_type.title} {block_type.description}".lower()
                if needle not in haystack:
                    continue
            matched.append(block_type)
        matched.sort(key=lambda t: (t.category_id, t.position if t.position is not None else 0))
        total = len(matched)
        return total, matched[offset:offset + limit]
