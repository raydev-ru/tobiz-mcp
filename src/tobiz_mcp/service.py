"""Прикладной слой: операции над сайтами, страницами и блоками.

Здесь нет ни MCP, ни HTTP-деталей: инструменты вызывают эти методы, а те работают с
нормализованными структурами (см. domain/ и tobiz/).
"""

from __future__ import annotations

import json
import time
from typing import Any

from . import errors, log
from .config import Config
from .domain import blocks as block_domain
from .domain.draft import Draft, DraftStore
from .render.bridge import RenderBridge
from .session import SessionStore
from .tobiz import endpoints as ep
from .tobiz import payload as payload_builder
from .tobiz import upload as upload_module
from .tobiz.catalog import BlockType, Catalog
from .tobiz.client import TobizClient
from .tobiz.envelope import blocks_from, json_field
from .tobiz.pages import Page, Project, parse_projects

logger = log.get("service")


class Service:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.store = SessionStore(config)
        self.store.load()
        self.client = TobizClient(config, self.store)
        self.bridge = RenderBridge(config)
        self.catalog = Catalog(config, self.client, self.bridge)
        self.drafts = DraftStore()
        self._projects: list[Project] | None = None
        self._counters = {"auth_relogin": 0, "upstream_error": 0, "render_failed": 0}

    async def aclose(self) -> None:
        await self.client.aclose()

    # --- сессия ---

    async def login(self, force: bool = True) -> dict[str, Any]:
        return await self.client.login(force=force)

    async def session_status(self) -> dict[str, Any]:
        return self.client.describe_session()

    # --- проекты и страницы ---

    async def projects(self, refresh: bool = False) -> list[Project]:
        await self.client.ensure_session()
        if self._projects is not None and not refresh:
            return self._projects
        envelope = await self.client.panel_ajax(ep.PANEL_AJAX_ACTION_PROJECTS)
        if not envelope.ok:
            raise errors.TobizError(errors.ACCESS_DENIED, "Не удалось получить список проектов",
                                    "Проверьте сессию: tobiz_login")
        html = envelope.payload.get("html") or ""
        projects = parse_projects(str(html), self.config.lp_template)
        self._projects = projects
        return projects

    async def project(self, project_id: str | None = None, refresh: bool = False) -> Project:
        projects = await self.projects(refresh=refresh)
        if project_id:
            self.check_allowed(project_id)
            for project in projects:
                if project.project_id == str(project_id):
                    return project
            raise errors.TobizError(
                errors.NOT_FOUND, f"Проект {project_id} не найден среди проектов аккаунта",
                "Вызовите tobiz_list_projects",
            )
        if len(projects) == 1:
            self.check_allowed(projects[0].project_id)
            return projects[0]
        raise errors.TobizError(
            errors.AMBIGUOUS_PROJECT,
            "В аккаунте несколько проектов — укажите project_id",
            "Список проектов: tobiz_list_projects",
        )

    def check_allowed(self, project_id: str) -> None:
        allowed = self.config.allowed_project_ids
        if allowed and str(project_id) not in allowed:
            raise errors.TobizError(
                errors.PROJECT_NOT_ALLOWED,
                f"Проект {project_id} не входит в TOBIZ_ALLOWED_PROJECT_IDS",
                "Измените белый список или работайте с разрешённым проектом",
            )

    async def pages(self, project_id: str | None = None, refresh: bool = False) -> tuple[Project, list[Page]]:
        project = await self.project(project_id, refresh=refresh)
        return project, project.pages

    async def resolve_page(self, project_id: str | None, page_id: str) -> tuple[str, Page]:
        project, pages = await self.pages(project_id)
        for page in pages:
            if page.page_id == str(page_id):
                return project.project_id, page
        raise errors.TobizError(
            errors.NOT_FOUND, f"Страница {page_id} не найдена в проекте {project.project_id}",
            "Вызовите tobiz_list_pages",
        )

    # --- блоки ---

    async def _editor_page_meta(self, project_id: str, page_id: str) -> dict[str, Any]:
        html = await self.client.fetch_text(self.config.editor_url(project_id, page_id))
        marker = "window.tobiz = "
        start = html.find(marker)
        if start < 0:
            return {}
        start += len(marker)
        end = html.find("</script>", start)
        raw = html[start:end].strip().rstrip(";")
        try:
            meta = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("window.tobiz не разобран", extra={"page_id": page_id})
            return {}
        return meta if isinstance(meta, dict) else {}

    async def draft(self, project_id: str, page_id: str, refresh: bool = False) -> Draft:
        existing = self.drafts.get(project_id, page_id)
        if existing is not None and not refresh:
            return existing
        meta = await self._editor_page_meta(project_id, page_id)
        draft = existing or self.drafts.create(project_id, page_id, meta)
        draft.page_meta.update(meta)
        envelope = await self.client.editor_ajax(
            ep.ACT_GET_BLOCKS, self.config.lp_base(project_id), page_id, rep_id=page_id)
        if not envelope.ok:
            raise errors.TobizError(
                errors.ACCESS_DENIED,
                f"Конструктор не отдал блоки страницы: {envelope.message or envelope.status}",
                "Проверьте сессию и доступ к странице",
            )
        raw_blocks = blocks_from(envelope)
        if refresh:
            draft.blocks.clear()
            draft.order.clear()
        self.drafts.load_blocks(draft, raw_blocks)
        return draft

    async def block_types(self, project_id: str) -> dict[str, BlockType]:
        return await self.catalog.types(project_id)

    async def type_or_raise(self, project_id: str, type_id: str) -> BlockType:
        types = await self.block_types(project_id)
        block_type = types.get(str(type_id))
        if block_type is None:
            raise errors.TobizError(
                errors.UNKNOWN_TYPE, f"Тип блока {type_id} отсутствует в сборке проекта",
                "Поиск по каталогу: tobiz_search_blocks",
            )
        if not block_type.has_template:
            raise errors.TobizError(
                errors.TEMPLATE_UNAVAILABLE,
                f"У типа {type_id} нет шаблона в этой сборке — рендер невозможен",
                "Выберите другой тип: tobiz_search_blocks",
            )
        return block_type

    def merged_values(self, block_type: BlockType, data: dict[str, Any],
                      server_defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        """Порядок важен: дефолты вендора -> серверные дефолты -> фактические значения."""
        merged: dict[str, Any] = dict(block_type.values)
        if server_defaults:
            merged.update(server_defaults)
        merged.update(data or {})
        return merged

    # --- изображения ---

    async def upload_image(self, project_id: str, page_id: str, block_id: str,
                           path: str | None = None, content_base64: str | None = None,
                           file_name: str | None = None) -> dict[str, Any]:
        # upload.php требует block_id: без него конструктор отвечает «Изображение не загружено! #2»,
        # и это легко принять за запрет загрузки тарифом (проверено живой загрузкой логотипа).
        if not str(block_id or "").strip():
            raise errors.TobizError(
                errors.BAD_ARGUMENT,
                "Не указан block_id: конструктор требует его при загрузке файла",
                "Возьмите block_id из tobiz_list_blocks или из ответа tobiz_add_block",
            )
        prepared = upload_module.prepare(self.config, path, content_base64, file_name)
        result = await self.client.upload_image(
            prepared.file_name, prepared.content, prepared.content_type, block_id,
            self.config.lp_base(project_id), page_id, project_id,
        )
        await self.audit("tobiz_upload_image", project_id, page_id=page_id, block_id=block_id,
                         extra={"filename": prepared.file_name, "bytes": prepared.size})
        return {
            "filename": result.get("image"),
            "bytes": prepared.size,
            "url_original": f"/img/original/{result.get('image')}",
            "url_325": f"/img/325x0/{result.get('image')}",
            "raw": result if result.get("msg") else None,
        }

    # --- сохранение ---

    async def save_page(self, project_id: str, page_id: str, verify: bool = True,
                        only_if_changed: bool = True,
                        expected_block_hashes: dict[str, str] | None = None,
                        include_payload: bool = False) -> dict[str, Any]:
        if self.config.read_only:
            raise errors.read_only()
        draft = await self.draft(project_id, page_id)
        if only_if_changed:
            draft.ensure_changes()
        if expected_block_hashes:
            for block_id, expected in expected_block_hashes.items():
                block = draft.blocks.get(str(block_id))
                if block is None:
                    raise errors.TobizError(errors.NOT_FOUND, f"Блок {block_id} исчез из черновика")
                current = json.dumps(block.values, ensure_ascii=False, sort_keys=True)
                import hashlib
                current_hash = hashlib.sha256(current.encode()).hexdigest()[:16]
                if current_hash != expected:
                    raise errors.TobizError(
                        errors.CONFLICT,
                        f"Блок {block_id} изменился после чтения (ожидался {expected})",
                        "Перечитайте блок и повторите правку",
                    )

        types = await self.block_types(project_id)
        items: list[dict[str, Any]] = []
        for block_id in draft.order:
            block = draft.blocks.get(block_id)
            if block is None:
                continue
            block_type = types.get(block.type_id)
            server_defaults: dict[str, Any] = {}
            if block_type is not None:
                try:
                    server_defaults = await self.catalog.default_values(project_id, block_type)
                except errors.TobizError:
                    server_defaults = {}
            base_values = block_type.values if block_type else {}
            values = {**base_values, **server_defaults, **block.values}
            items.append({"block_id": block_id, "type_id": block.type_id, "values": values})

        project_dir = self.catalog.project_dir(project_id) / "bundles"
        project_dir.mkdir(parents=True, exist_ok=True)
        try:
            rendered = await self.bridge.render(project_dir, items)
        except errors.TobizError:
            self._counters["render_failed"] += 1
            raise

        for block_id, html in rendered.items():
            block = draft.blocks.get(block_id)
            if block is not None:
                # старый cache сохраняем на случай повторного сохранения без рендера
                block.cache = html

        payload = payload_builder.build(draft, rendered)
        if self.config.dry_run or include_payload:
            preview = {
                "blocks": len(payload["userBlocks"]),
                "changed": draft.changed_blocks,
                "change_hash": draft.change_hash(),
                "payload": payload if include_payload else None,
            }
            if self.config.dry_run:
                preview["dry_run"] = True
                return preview

        envelope = await self.client.editor_ajax(
            ep.ACT_SAVE_BLOCKS, self.config.lp_base(project_id), page_id,
            data=json.dumps(payload, ensure_ascii=False))
        if not envelope.ok:
            raise errors.TobizError(
                errors.SAVE_FAILED,
                f"Конструктор не сохранил страницу: {envelope.message or envelope.status}",
                "Черновик сохранён в памяти: повторите tobiz_save_page",
                raw={"status": envelope.status, "body": envelope.raw_text[:500]},
            )

        change_hash = draft.change_hash()
        # счётчики считаем ДО сброса правок: иначе ответ сообщает «изменено 0 блоков»
        changed_blocks = list(draft.changed_blocks)
        for block_id in changed_blocks:
            draft.blocks[block_id].changed_paths = []
        await self.audit("tobiz_save_page", project_id, page_id=page_id,
                         extra={"blocks_total": len(items), "blocks_changed": len(changed_blocks),
                                "change_hash": change_hash, "result": "ok"})

        result: dict[str, Any] = {
            "saved": True,
            "blocks_total": len(items),
            "blocks_changed": len(changed_blocks),
            "change_hash": change_hash,
            "response": envelope.message or envelope.status,
        }
        if verify:
            result["verify"] = await self.verify_page(project_id, page_id)
        if include_payload:
            result["payload"] = payload
        return result

    # --- верификация ---

    async def verify_page(self, project_id: str, page_id: str,
                          expect: list[str] | None = None,
                          block_ids: list[str] | None = None) -> dict[str, Any]:
        try:
            html = await self.client.fetch_text(self.config.public_url(project_id, page_id))
        except errors.TobizError as exc:
            return {"status": "unavailable", "reason": exc.message}
        found: list[str] = []
        missing: list[str] = []
        for needle in expect or []:
            (found if needle in html else missing).append(needle)
        blocks_report: dict[str, bool] = {}
        for block_id in block_ids or []:
            blocks_report[str(block_id)] = f'id="b_{block_id}"' in html
        status = "ok"
        if missing or not all(blocks_report.values()):
            status = "mismatch"
        return {"status": status, "bytes": len(html), "found": found, "missing": missing,
                "blocks": blocks_report or None}

    # --- журнал ---

    async def audit(self, tool: str, project_id: str, page_id: str | None = None,
                    block_id: str | None = None, extra: dict[str, Any] | None = None) -> None:
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tool": tool,
            "project_id": str(project_id),
            "page_id": str(page_id) if page_id else None,
            "block_id": str(block_id) if block_id else None,
        }
        record.update(extra or {})
        try:
            self.config.audit_dir.mkdir(parents=True, exist_ok=True)
            with (self.config.audit_dir / "audit.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:  # журнал не должен ломать операцию
            logger.warning("журнал недоступен: %s", exc)

    async def health(self) -> dict[str, Any]:
        from . import __version__

        return {
            "version": __version__,
            "transport": self.config.transport,
            "read_only": self.config.read_only,
            "dry_run": self.config.dry_run,
            "session": self.client.describe_session(),
            "assets_dir": str(self.config.assets_dir),
            "renderer_available": self.bridge.available,
            "counters": dict(self._counters),
        }
