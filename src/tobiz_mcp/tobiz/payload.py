"""Сборка payload-а SaveBlocks — ровно в том виде, в каком его отправляет редактор.

Формат разобран по обработчику кнопки «Сохранить» в editor.min.js и подтверждён живым
сохранением (историю правок см. в описании репозитория).
"""

from __future__ import annotations

import json
from typing import Any

from ..domain.draft import Draft

SEO_NAME_MAP = {
    "page_seo_title": "seo_title",
    "page_seo_keywords": "seo_keywords",
    "page_seo_description": "seo_description",
}

PAGE_META_KEYS = (
    "page_config", "articles_on", "project_domain", "page_title", "page_dir",
    "personal_seo_configs", "access_control", "valid_login", "valid_password", "OG_image",
)


def build(draft: Draft, rendered: dict[str, str]) -> dict[str, Any]:
    """rendered: {block_id: html} для всех блоков, которые уходят на сервер."""
    user_blocks: list[dict[str, Any]] = []
    for index, block_id in enumerate(draft.order):
        block = draft.blocks.get(block_id)
        if block is None:
            continue
        cache = rendered.get(block_id)
        if cache is None:
            cache = block.cache
        user_blocks.append({
            "id": block_id,
            "user_id": block.user_id,
            "sort_id": index,
            "type_id": block.type_id,
            "page_id": draft.page_id,
            "save": 0,
            "cache": cache,
            # значения уходят объектом: редактор держит их в памяти разобранными
            # (конструктор принимает data и строкой, и объектом)
            "data": block.values,
            "deleted": "1" if block.deleted else "0",
        })

    payload: dict[str, Any] = {
        "rep_id": draft.page_id,
        "lcpImage": lcp_image(rendered),
        "userBlocks": user_blocks,
    }
    for key in PAGE_META_KEYS:
        payload[key] = draft.page_meta.get(key)
    for target, source in SEO_NAME_MAP.items():
        payload[target] = draft.page_meta.get(source)
    return payload


def lcp_image(rendered: dict[str, str]) -> str:
    """URL фонового изображения первого блока (редактор вычисляет то же самое из DOM)."""
    import re

    for html in rendered.values():
        match = re.search(r"background-image:\s*url\((['\"]?)(.*?)\1\)", html or "")
        if match:
            url = match.group(2).replace("/img/1920x0/", "")
            if url and "null.png" not in url:
                return url
    return ""
