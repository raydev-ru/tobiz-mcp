"""Доменная модель блока: схема полей, значения, точечные правки."""

from __future__ import annotations

import copy
import re
from typing import Any

from ..errors import BAD_ARGUMENT, UNKNOWN_FIELD, TobizError

_SELECT_TYPES = {
    "select", "select_bg_repeat", "select_bg_size", "select_font_weight",
    "select_clip_path", "color", "colors",
}
_META_TYPES = {"subtitle", "devider", "instruction", "more_info"}
_INT_TYPES = {"int", "range"}
_IMAGE_TYPES = {"image_gallery", "image"}


def field_schema(block_type: Any, current: dict[str, Any] | None = None,
                 only: str = "all") -> dict[str, Any]:
    """Схема полей типа блока для агента: имя, тип, русская подпись, дефолт, текущее значение."""
    current = current or {}
    fields: list[dict[str, Any]] = []
    for setting in block_type.settings or []:
        name = setting.get("name")
        stype = setting.get("type") or "text"
        if not name or stype in _META_TYPES:
            continue
        default = block_type.values.get(name)
        value = current.get(name, default)
        if only == "changed" and name not in current:
            continue
        entry: dict[str, Any] = {
            "name": name,
            "type": stype,
            "title": setting.get("title") or "",
        }
        if default is not None:
            entry["default"] = default
        if name in current:
            entry["current"] = current[name]
        if setting.get("require"):
            entry["require"] = setting["require"]
        options = setting.get("vars")
        if isinstance(options, list) and options:
            entry["options"] = [o.get("val") for o in options if isinstance(o, dict)]
        if stype in _IMAGE_TYPES:
            entry["hint"] = "значение — имя файла, полученное tobiz_upload_image"
        fields.append(entry)

    vars_info = []
    for var in block_type.vars or []:
        name = var.get("name")
        if not name:
            continue
        value = current.get(name, block_type.values.get(name))
        info = {"name": name, "editor": var.get("editor") or var.get("type") or ""}
        if isinstance(value, list):
            info["items"] = len(value)
        elif isinstance(value, dict):
            info["keys"] = sorted(value.keys())[:12]
        vars_info.append(info)

    return {
        "type_id": block_type.type_id,
        "title": block_type.title,
        "description": block_type.description,
        "has_template": block_type.has_template,
        "fields": fields,
        "vars": vars_info,
        "fields_count": len(fields),
    }


def unknown_fields(block_type: Any, keys: list[str]) -> list[str]:
    known = {s.get("name") for s in (block_type.settings or []) if s.get("name")}
    known |= {v.get("name") for v in (block_type.vars or []) if v.get("name")}
    known |= set((block_type.values or {}).keys())
    known |= {"anchor", "flexblocks"}
    return [k for k in keys if k not in known]


def _get(values: Any, path: str) -> Any:
    node = values
    for part in [p for p in path.split("/") if p != ""]:
        if isinstance(node, list):
            node = node[int(part)]
        elif isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def _set(values: Any, path: str, value: Any, replace: bool) -> None:
    parts = [p for p in path.split("/") if p != ""]
    if not parts:
        raise TobizError(BAD_ARGUMENT, "Пустой путь правки", "Указывайте путь вида /arr1/0/title")
    node = values
    for part in parts[:-1]:
        if isinstance(node, list):
            node = node[int(part)]
        else:
            if part not in node or not isinstance(node[part], (dict, list)):
                node[part] = {}
            node = node[part]
    last = parts[-1]
    if isinstance(node, list):
        index = int(last)
        if replace or index >= len(node):
            node[index] = value
        elif isinstance(node[index], dict) and isinstance(value, dict):
            node[index] = {**node[index], **value}
        else:
            node[index] = value
    else:
        if not replace and isinstance(node.get(last), dict) and isinstance(value, dict):
            node[last] = {**node[last], **value}
        else:
            node[last] = value


def apply_edits(values: dict[str, Any], patch: dict[str, Any] | None = None,
                ops: list[dict[str, Any]] | None = None,
                replace: bool = False) -> tuple[dict[str, Any], list[str]]:
    """Возвращает новые значения и список изменённых путей."""
    result = copy.deepcopy(values)
    changed: list[str] = []
    for name, value in (patch or {}).items():
        before = result.get(name)
        if not replace and isinstance(before, dict) and isinstance(value, dict):
            result[name] = {**before, **value}
        else:
            result[name] = copy.deepcopy(value)
        if result[name] != before:
            changed.append(name)
    for op in ops or []:
        path = str(op.get("path") or "")
        if not path.startswith("/"):
            raise TobizError(BAD_ARGUMENT, f"Путь должен начинаться с «/»: {path!r}",
                             "Пример: {\"path\": \"/arr1/0/title\", \"value\": \"Заголовок\"}")
        before = _get(result, path)
        _set(result, path, copy.deepcopy(op.get("value")), replace)
        if _get(result, path) != before:
            changed.append(path)
    return result, changed


_IMG_NAME_RE = re.compile(r"^[A-Za-z0-9._\-()\u0400-\u04FF ]{1,200}$")


def validate_values(block_type: Any, values: dict[str, Any]) -> None:
    """Мягкая проверка: неизвестные поля и значения select вне списка — ошибка."""
    settings = {s.get("name"): s for s in (block_type.settings or []) if s.get("name")}
    unknown = unknown_fields(block_type, list(values))
    if unknown:
        raise TobizError(
            UNKNOWN_FIELD,
            f"Поля не найдены в схеме блока {block_type.type_id}: {', '.join(unknown)}",
            "Список допустимых полей — в tobiz_describe_block",
            raw={"unknown": unknown,
                 "known": sorted(k for k in settings if k)},
        )
    for name, value in values.items():
        setting = settings.get(name) or {}
        stype = setting.get("type") or ""
        options = setting.get("vars")
        if stype in _SELECT_TYPES - {"color", "colors"} and isinstance(options, list):
            allowed = [o.get("val") for o in options if isinstance(o, dict)]
            if allowed and value not in allowed and value not in ("", None):
                raise TobizError(
                    BAD_ARGUMENT,
                    f"Значение {value!r} недопустимо для поля {name}",
                    f"Допустимые значения: {', '.join(str(a) for a in allowed)}",
                )
        if stype in _INT_TYPES and value not in ("", None):
            try:
                float(value)
            except (TypeError, ValueError):
                raise TobizError(BAD_ARGUMENT, f"Поле {name} ожидает число, получено {value!r}")
