"""MCP-инструменты: тонкий слой над Service (схемы, валидация, формат ответов).

Имена инструментов нейтральны по возможности (tobiz_*), не по потребителю.
"""

from __future__ import annotations

import functools
import time
from typing import Annotated, Any, Callable

from . import errors, log
from .domain import blocks as block_domain
from .service import Service

logger = log.get("tools")

from pydantic import BeforeValidator, WithJsonSchema

SCHEMA_VERSION = 1

# Идентификаторы конструктора — строки, но LLM-клиенты естественно передают числа, и клиентская
# валидация по JSON-схеме отсекает int у поля с типом string. Поэтому схема объявляет оба типа
# (WithJsonSchema), а BeforeValidator приводит значение к строке до бизнес-логики.
Id = Annotated[
    str,
    BeforeValidator(lambda value: "" if value is None else str(value)),
    WithJsonSchema({"type": ["string", "integer"]}),
]
READ_TOOLS = {
    "tobiz_login", "tobiz_session_status", "tobiz_health", "tobiz_list_projects",
    "tobiz_list_pages", "tobiz_page_summary", "tobiz_list_blocks", "tobiz_get_block",
    "tobiz_search_blocks", "tobiz_describe_block", "tobiz_verify_page", "tobiz_refresh_assets",
}


def _envelope(data: Any, started: float, **extra: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "duration_ms": int((time.time() - started) * 1000),
    }
    meta.update(extra)
    return {"ok": True, "data": data, "meta": meta}


def _error(exc: Exception, started: float) -> dict[str, Any]:
    if isinstance(exc, errors.TobizError):
        payload = exc.to_dict()
    else:  # неожиданное — не показываем трассу агенту, но логируем
        logger.exception("необработанная ошибка")
        payload = {"code": errors.INTERNAL, "message": str(exc)}
    return {"ok": False, "error": payload,
            "meta": {"schema_version": SCHEMA_VERSION,
                     "duration_ms": int((time.time() - started) * 1000)}}


def wrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Оборачивает метод сервиса в конверт {ok, data|error, meta}.

    Важно: functools.wraps сохраняет сигнатуру исходной функции (`__wrapped__`), иначе MCP
    построит схему инструмента из `*args/**kwargs` и клиент не сможет передать параметры.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        started = time.time()
        try:
            result = await func(*args, **kwargs)
            if isinstance(result, dict) and "ok" in result:
                return result
            return _envelope(result, started)
        except Exception as exc:  # noqa: BLE001 — конверт нужен всегда
            return _error(exc, started)

    return wrapper


def register(mcp: Any, service: Service) -> list[str]:
    """Регистрирует инструменты и возвращает список их имён."""
    read_only = service.config.read_only
    registered: list[str] = []

    def tool(name: str, description: str):
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            if read_only and name not in READ_TOOLS:
                return func
            mcp.tool(name=name, description=description)(wrap(func))
            registered.append(name)
            return func
        return decorator

    # --- служебные ---

    @tool("tobiz_login",
          "Войти в конструктор (или принудительно обновить сессию). Возвращает состояние сессии "
          "без значений cookie.")
    async def tobiz_login(force: bool = True) -> dict[str, Any]:
        return await service.login(force=force)

    @tool("tobiz_session_status",
          "Состояние сессии конструктора: есть ли cookie, когда проверялись, какой user_id.")
    async def tobiz_session_status() -> dict[str, Any]:
        return await service.session_status()

    @tool("tobiz_health",
          "Версия сервиса, режимы, состояние сессии, доступность рендерера, счётчики ошибок.")
    async def tobiz_health() -> dict[str, Any]:
        return await service.health()

    # --- чтение структуры ---

    @tool("tobiz_list_projects",
          "Список проектов (сайтов) аккаунта: project_id, название, адрес сайта, число страниц. "
          "project_id нужен всем остальным инструментам.")
    async def tobiz_list_projects(include_pages: bool = False,
                                  refresh: bool = False) -> dict[str, Any]:
        projects = await service.projects(refresh=refresh)
        return {
            "projects": [p.to_dict(service.config.lp_template, include_pages) for p in projects],
            "count": len(projects),
        }

    @tool("tobiz_list_pages",
          "Страницы проекта: page_id (он же v в адресе редактора), название, slug, видимость, "
          "ссылка редактора.")
    async def tobiz_list_pages(project_id: Id | None = None,
                               refresh: bool = False) -> dict[str, Any]:
        project, pages = await service.pages(project_id, refresh=refresh)
        return {
            "project_id": project.project_id,
            "pages": [p.to_dict(service.config.lp_template, project.project_id) for p in pages],
            "count": len(pages),
        }

    @tool("tobiz_list_blocks",
          "Блоки страницы в порядке отображения: block_id, type_id, название типа, позиция, "
          "признак правки в черновике. values=true добавляет значения полей.")
    async def tobiz_list_blocks(project_id: Id | None = None, page_id: Id = "",
                                values: bool = False) -> dict[str, Any]:
        project_id, _ = await service.resolve_page(project_id, page_id)
        draft = await service.draft(project_id, page_id)
        types = await service.block_types(project_id)
        items = []
        for block_id in draft.order:
            block = draft.blocks[block_id]
            block_type = types.get(block.type_id)
            item = {
                "block_id": block.block_id,
                "type_id": block.type_id,
                "type_title": block_type.title if block_type else "",
                "position": block.position,
                "sort_id": block.sort_id,
                "deleted": block.deleted,
                "changed": bool(block.changed_paths) or block.origin == "created",
            }
            if values:
                item["values"] = block.values
            items.append(item)
        return {"page_id": page_id, "blocks": items, "count": len(items),
                "pending_changes": draft.changed_blocks}

    @tool("tobiz_get_block",
          "Значения полей блока. with_schema=true добавляет подписи и типы полей.")
    async def tobiz_get_block(project_id: Id | None = None, page_id: Id = "",
                              block_id: Id = "", with_schema: bool = False) -> dict[str, Any]:
        project_id, _ = await service.resolve_page(project_id, page_id)
        draft = await service.draft(project_id, page_id)
        block = draft.blocks.get(str(block_id))
        if block is None:
            raise errors.TobizError(errors.NOT_FOUND, f"Блок {block_id} не найден на странице",
                                    "Состав страницы: tobiz_list_blocks")
        data: dict[str, Any] = {
            "block_id": block.block_id,
            "type_id": block.type_id,
            "values": block.values,
            "changed": bool(block.changed_paths) or block.origin == "created",
        }
        if with_schema:
            block_type = await service.type_or_raise(project_id, block.type_id)
            data["schema"] = block_domain.field_schema(block_type, block.values)
        return data

    @tool("tobiz_page_summary",
          "Компактная карта страницы: порядок блоков и короткий текст каждого — экономит контекст.")
    async def tobiz_page_summary(project_id: Id | None = None, page_id: Id = "",
                                 max_chars_per_block: int = 160) -> dict[str, Any]:
        project_id, page = await service.resolve_page(project_id, page_id)
        draft = await service.draft(project_id, page_id)
        types = await service.block_types(project_id)
        summary = []
        for block_id in draft.order:
            block = draft.blocks[block_id]
            block_type = types.get(block.type_id)
            summary.append({
                "block_id": block.block_id,
                "type_id": block.type_id,
                "type_title": block_type.title if block_type else "",
                "snippet": _snippet(block.values, max_chars_per_block),
                "changed": bool(block.changed_paths) or block.origin == "created",
            })
        return {"project_id": project_id, "page_id": page_id, "title": page.title,
                "url": page.url, "blocks": summary}

    @tool("tobiz_search_blocks",
          "Поиск по библиотеке блоков: русский текст ищется в названии и описании типа, "
          "можно отфильтровать по категории или точному type_id.")
    async def tobiz_search_blocks(project_id: Id | None = None, query: str = "",
                                  category_id: Id = "", type_id: Id = "",
                                  limit: int = 20, offset: int = 0) -> dict[str, Any]:
        project = await service.project(project_id)
        types = await service.block_types(project.project_id)
        limit = max(1, min(int(limit or 20), 100))
        total, items = service.catalog.search(types, query, category_id, type_id, limit, offset)
        return {"total": total, "limit": limit, "offset": offset,
                "items": [t.to_public() for t in items]}

    @tool("tobiz_describe_block",
          "Схема полей типа блока: имена, русские подписи, типы, значения по умолчанию и текущие. "
          "only=changed — только поля, отличающиеся от дефолта. Достаточно указать type_id "
          "либо пару page_id + block_id (тип возьмётся из блока).")
    async def tobiz_describe_block(project_id: Id | None = None, type_id: Id = "",
                                   page_id: Id = "", block_id: Id = "",
                                   only: str = "all") -> dict[str, Any]:
        project = await service.project(project_id)
        current: dict[str, Any] = {}
        if not type_id:
            if not (page_id and block_id):
                raise errors.TobizError(
                    errors.BAD_ARGUMENT,
                    "Укажите type_id либо пару page_id + block_id",
                    "Список типов: tobiz_search_blocks; состав страницы: tobiz_list_blocks",
                )
            await service.resolve_page(project.project_id, page_id)
            draft = await service.draft(project.project_id, page_id)
            block = draft.blocks.get(str(block_id))
            if block is None:
                raise errors.TobizError(errors.NOT_FOUND, f"Блок {block_id} не найден на странице")
            type_id = block.type_id
        block_type = await service.type_or_raise(project.project_id, type_id)
        if page_id and block_id:
            await service.resolve_page(project.project_id, page_id)
            draft = await service.draft(project.project_id, page_id)
            block = draft.blocks.get(str(block_id))
            if block is None:
                raise errors.TobizError(errors.NOT_FOUND, f"Блок {block_id} не найден на странице")
            current = block.values
        schema = block_domain.field_schema(block_type, current, only=only)
        if not current:
            schema["defaults_from_server"] = bool(
                await service.catalog.default_values(project.project_id, block_type))
        return schema

    @tool("tobiz_refresh_assets",
          "Принудительно перекачать библиотеку блоков и каталог проекта (если вендор обновил сборку).")
    async def tobiz_refresh_assets(project_id: Id | None = None) -> dict[str, Any]:
        project = await service.project(project_id)
        index = await service.catalog.ensure_assets(project.project_id, force=True)
        types = await service.block_types(project.project_id)
        return {"project_id": project.project_id, "files": index.get("files", {}),
                "types": len(types)}

    # --- запись ---

    @tool("tobiz_add_block",
          "Добавить блок из библиотеки на страницу (в конец или после указанного блока). "
          "Блок попадает в черновик: на сайте появится после tobiz_save_page.")
    async def tobiz_add_block(project_id: Id | None = None, page_id: Id = "",
                              type_id: Id = "", after_block_id: Id = "",
                              values: dict[str, Any] | None = None) -> dict[str, Any]:
        if service.config.read_only:
            raise errors.read_only()
        project_id, _ = await service.resolve_page(project_id, page_id)
        block_type = await service.type_or_raise(project_id, type_id)
        draft = await service.draft(project_id, page_id)
        server_defaults = await service.catalog.default_values(project_id, block_type)
        base = service.merged_values(block_type, {}, server_defaults)
        if values:
            block_domain.validate_values(block_type, values)
            merged, changed = block_domain.apply_edits(base, values)
        else:
            merged, changed = base, []
        envelope = await service.client.editor_ajax(
            "CreateNewBlock", service.config.lp_base(project_id), page_id,
            rep_id=page_id, type_id=block_type.type_id)
        if not envelope.ok:
            raise errors.TobizError(
                errors.SAVE_FAILED,
                f"Конструктор не создал блок: {envelope.message or envelope.status}",
                "Повторите попытку; при устойчивой ошибке проверьте тариф/лимиты аккаунта",
            )
        created = envelope.payload.get("respons")
        block_id = ""
        if isinstance(created, str):
            try:
                import json
                block_id = str(json.loads(created).get("block_id") or "")
            except Exception:  # noqa: BLE001
                block_id = ""
        if not block_id:
            raise errors.TobizError(errors.SAVE_FAILED,
                                    "Конструктор не вернул block_id нового блока",
                                    raw=envelope.raw_text[:300])
        block = draft.add_created(block_id, block_type.type_id, merged,
                                  after_block_id or None)
        block.changed_paths = changed
        return {"block_id": block.block_id, "type_id": block.type_id, "sort_id": block.sort_id,
                "changed_fields": changed, "pending_save": True}

    @tool("tobiz_update_block",
          "Изменить поля блока: values — слияние по именам полей, set — точечные правки путями "
          "(например /arr1/0/title). Непереданные поля не теряются.")
    async def tobiz_update_block(project_id: Id | None = None, page_id: Id = "",
                                 block_id: Id = "", values: dict[str, Any] | None = None,
                                 set: list[dict[str, Any]] | None = None,
                                 replace: bool = False) -> dict[str, Any]:
        if service.config.read_only:
            raise errors.read_only()
        if not values and not set:
            raise errors.TobizError(errors.BAD_ARGUMENT, "Передайте values или set")
        project_id, _ = await service.resolve_page(project_id, page_id)
        draft = await service.draft(project_id, page_id)
        block = draft.blocks.get(str(block_id))
        if block is None:
            raise errors.TobizError(errors.NOT_FOUND, f"Блок {block_id} не найден на странице",
                                    "Состав страницы: tobiz_list_blocks")
        block_type = await service.type_or_raise(project_id, block.type_id)
        if values:
            block_domain.validate_values(block_type, values)
        merged, changed = block_domain.apply_edits(block.values, values, set, replace)
        block.values = merged
        for path in changed:
            if path not in block.changed_paths:
                block.changed_paths.append(path)
        return {"block_id": block.block_id, "changed_fields": changed,
                "change_hash": draft.change_hash()}

    @tool("tobiz_delete_block",
          "Удалить блок со страницы (в черновике; на сайте — после tobiz_save_page).")
    async def tobiz_delete_block(project_id: Id | None = None, page_id: Id = "",
                                 block_id: Id = "") -> dict[str, Any]:
        if service.config.read_only:
            raise errors.read_only()
        project_id, _ = await service.resolve_page(project_id, page_id)
        draft = await service.draft(project_id, page_id)
        draft.remove_block(str(block_id))
        return {"block_id": str(block_id), "deleted": True,
                "change_hash": draft.change_hash()}

    @tool("tobiz_move_block",
          "Изменить порядок блоков: position (индекс с нуля) или after_block_id.")
    async def tobiz_move_block(project_id: Id | None = None, page_id: Id = "",
                               block_id: Id = "", position: int | None = None,
                               after_block_id: Id = "") -> dict[str, Any]:
        if service.config.read_only:
            raise errors.read_only()
        project_id, _ = await service.resolve_page(project_id, page_id)
        draft = await service.draft(project_id, page_id)
        order = draft.move_block(str(block_id), position, after_block_id or None)
        return {"order": order, "change_hash": draft.change_hash()}

    @tool("tobiz_save_page",
          "Единственный инструмент, который пишет на сервер: рендерит HTML блоков шаблонами "
          "вендора и отправляет SaveBlocks. verify=true проверяет результат по публичной вёрстке.")
    async def tobiz_save_page(project_id: Id | None = None, page_id: Id = "",
                              verify: bool = True, only_if_changed: bool = True,
                              include_payload: bool = False) -> dict[str, Any]:
        project_id, _ = await service.resolve_page(project_id, page_id)
        return await service.save_page(project_id, page_id, verify=verify,
                                       only_if_changed=only_if_changed,
                                       include_payload=include_payload)

    @tool("tobiz_discard_changes",
          "Забыть несохранённые правки страницы и перечитать её с сервера.")
    async def tobiz_discard_changes(project_id: Id | None = None,
                                    page_id: Id = "") -> dict[str, Any]:
        project_id, _ = await service.resolve_page(project_id, page_id)
        service.drafts.drop(project_id, page_id)
        draft = await service.draft(project_id, page_id, refresh=True)
        return {"page_id": page_id, "blocks": len(draft.blocks), "discarded": True}

    # --- проверка и изображения ---

    @tool("tobiz_verify_page",
          "Проверить публичную вёрстку страницы: наличие блоков и ожидаемых текстов.")
    async def tobiz_verify_page(project_id: Id | None = None, page_id: Id = "",
                                expect: list[str] | None = None,
                                block_ids: list[str] | None = None) -> dict[str, Any]:
        project_id, _ = await service.resolve_page(project_id, page_id)
        if not block_ids:
            draft = await service.draft(project_id, page_id)
            block_ids = [b for b in draft.order]
        return await service.verify_page(project_id, page_id, expect, block_ids)

    @tool("tobiz_upload_image",
          "Загрузить изображение в конструктор. path — файл внутри /data/inbox, либо "
          "content_base64. Возвращает имя файла для полей image/image_gallery.")
    async def tobiz_upload_image(project_id: Id | None = None, page_id: Id = "",
                                 block_id: Id = "", path: str = "",
                                 content_base64: str = "", file_name: str = "") -> dict[str, Any]:
        if service.config.read_only:
            raise errors.read_only()
        project = await service.project(project_id)
        if page_id:
            await service.resolve_page(project.project_id, page_id)
        return await service.upload_image(
            project.project_id, page_id or "", block_id, path or None,
            content_base64 or None, file_name or None)

    @tool("tobiz_set_block_image",
          "Загрузить изображение и подставить его имя в указанное поле блока одним вызовом.")
    async def tobiz_set_block_image(project_id: Id | None = None, page_id: Id = "",
                                    block_id: Id = "", field: str = "",
                                    path: str = "", content_base64: str = "",
                                    file_name: str = "") -> dict[str, Any]:
        if service.config.read_only:
            raise errors.read_only()
        project_id, _ = await service.resolve_page(project_id, page_id)
        uploaded = await service.upload_image(
            project_id, page_id, block_id, path or None, content_base64 or None,
            file_name or None)
        draft = await service.draft(project_id, page_id)
        block = draft.blocks.get(str(block_id))
        if block is None:
            raise errors.TobizError(errors.NOT_FOUND, f"Блок {block_id} не найден на странице")
        block_type = await service.type_or_raise(project_id, block.type_id)
        block_domain.validate_values(block_type, {field: uploaded["filename"]})
        merged, changed = block_domain.apply_edits(block.values, {field: uploaded["filename"]})
        block.values = merged
        for path_name in changed:
            if path_name not in block.changed_paths:
                block.changed_paths.append(path_name)
        return {"filename": uploaded["filename"], "url_325": uploaded["url_325"],
                "field": field, "changed_fields": changed,
                "change_hash": draft.change_hash()}

    return registered


def _snippet(values: dict[str, Any], limit: int) -> str:
    """Короткий человекочитаемый текст блока: собираем строковые значения верхнего уровня."""
    parts: list[str] = []
    for key in ("title", "h1", "h2", "header", "text", "text1", "text2", "subtitle",
                "description", "logo_text", "btn_text", "phone1", "email"):
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    for key, value in values.items():
        if len(parts) >= 6:
            break
        if isinstance(value, list) and value and isinstance(value[0], dict):
            for item in value[:3]:
                title = item.get("title") or item.get("name")
                if isinstance(title, str) and title.strip():
                    parts.append(title.strip())
    text = " | ".join(parts) or (values.get("anchor") or "")
    text = " ".join(str(text).split())
    return text[:limit]
