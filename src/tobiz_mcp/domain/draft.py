"""Черновик страницы: правки копятся в памяти, на сервер уходят только по tobiz_save_page."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from ..errors import NO_CHANGES, NOT_FOUND, TobizError


@dataclass
class DraftBlock:
    block_id: str
    type_id: str
    values: dict[str, Any]
    origin: str = "server"          # server | created
    cache: str = ""
    position: int = 0
    sort_id: int = 0
    user_id: str = ""
    deleted: bool = False
    changed_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "type_id": self.type_id,
            "origin": self.origin,
            "position": self.position,
            "sort_id": self.sort_id,
            "deleted": self.deleted,
            "changed": bool(self.changed_paths) or self.origin == "created",
        }


@dataclass
class Draft:
    project_id: str
    page_id: str
    page_meta: dict[str, Any] = field(default_factory=dict)
    blocks: dict[str, DraftBlock] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    base_hash: str = ""

    # --- работа с составом ---

    def add_created(self, block_id: str, block_type_id: str, values: dict[str, Any],
                    after_block_id: str | None = None) -> DraftBlock:
        block = DraftBlock(block_id=block_id, type_id=block_type_id, values=values,
                           origin="created")
        self.blocks[block_id] = block
        if after_block_id and after_block_id in self.order:
            index = self.order.index(after_block_id) + 1
            self.order.insert(index, block_id)
        else:
            self.order.append(block_id)
        self._reindex()
        return block

    def remove_block(self, block_id: str) -> None:
        if block_id not in self.blocks:
            raise TobizError(NOT_FOUND, f"Блок {block_id} не найден на странице",
                             "Перечитайте состав: tobiz_list_blocks")
        self.blocks[block_id].deleted = True

    def move_block(self, block_id: str, position: int | None = None,
                   after_block_id: str | None = None) -> list[str]:
        if block_id not in self.order:
            raise TobizError(NOT_FOUND, f"Блок {block_id} не найден на странице")
        self.order.remove(block_id)
        if after_block_id and after_block_id in self.order:
            self.order.insert(self.order.index(after_block_id) + 1, block_id)
        elif position is not None:
            self.order.insert(max(0, min(position, len(self.order))), block_id)
        else:
            self.order.append(block_id)
        self._reindex()
        return list(self.order)

    def _reindex(self) -> None:
        for index, block_id in enumerate(self.order):
            if block_id in self.blocks:
                self.blocks[block_id].sort_id = index

    # --- состояние ---

    @property
    def changed_blocks(self) -> list[str]:
        return [bid for bid, b in self.blocks.items()
                if b.changed_paths or b.origin == "created"]

    @property
    def has_changes(self) -> bool:
        return any(b.changed_paths or b.origin == "created" or b.deleted
                   for b in self.blocks.values())

    def change_hash(self) -> str:
        payload = [
            {
                "block_id": bid,
                "type_id": b.type_id,
                "deleted": b.deleted,
                "sort_id": b.sort_id,
                "values": b.values,
            }
            for bid, b in sorted(self.blocks.items())
        ]
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]

    def discard(self) -> None:
        self.blocks.clear()
        self.order.clear()

    def ensure_changes(self) -> None:
        if not self.has_changes:
            raise TobizError(
                NO_CHANGES,
                "В черновике нет изменений — сохранять нечего",
                "Сначала измените блок: tobiz_update_block / tobiz_add_block / tobiz_delete_block",
            )


class DraftStore:
    """Черновики живут в памяти процесса (ADR-5): несохранённое не переживает рестарт."""

    def __init__(self) -> None:
        self._drafts: dict[tuple[str, str], Draft] = {}

    def get(self, project_id: str, page_id: str) -> Draft | None:
        return self._drafts.get((str(project_id), str(page_id)))

    def create(self, project_id: str, page_id: str, page_meta: dict[str, Any]) -> Draft:
        draft = Draft(project_id=str(project_id), page_id=str(page_id), page_meta=page_meta)
        self._drafts[(draft.project_id, draft.page_id)] = draft
        return draft

    def drop(self, project_id: str, page_id: str) -> None:
        self._drafts.pop((str(project_id), str(page_id)), None)

    def load_blocks(self, draft: Draft, blocks: list[dict[str, Any]]) -> None:
        """Наполняет черновик блоками, пришедшими из GetBlocks (data уже развёрнут)."""
        draft.blocks.clear()
        draft.order.clear()
        for raw in blocks:
            block_id = str(raw.get("id"))
            values = copy.deepcopy(raw.get("data_obj") or {})
            draft.blocks[block_id] = DraftBlock(
                block_id=block_id,
                type_id=str(raw.get("type_id")),
                values=values,
                cache=str(raw.get("cache") or ""),
                position=int(raw.get("position") or 0),
                sort_id=int(raw.get("sort_id") or 0),
                user_id=str(raw.get("user_id") or ""),
                deleted=str(raw.get("deleted") or "0") == "1",
            )
            draft.order.append(block_id)
        draft.order.sort(key=lambda bid: draft.blocks[bid].sort_id)
        draft._reindex()
        draft.base_hash = draft.change_hash()
