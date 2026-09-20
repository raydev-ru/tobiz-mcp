"""HTTP-клиент конструктора: сессия, релогин, разбор ответов.

Единственный модуль, который знает про cookie, заголовки браузера и адреса эндпоинтов.
Всё, что выше, работает с Envelope и доменными структурами.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from .. import errors, log
from ..config import Config
from ..session import SessionStore
from . import endpoints as ep
from .envelope import ACCESS_DENIED, Envelope, parse

logger = log.get("tobiz.client")


class TobizClient:
    def __init__(self, config: Config, store: SessionStore) -> None:
        self.config = config
        self.store = store
        self._lock = asyncio.Lock()
        self._login_attempts = 0
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=httpx.Timeout(config.http_timeout, connect=config.http_connect_timeout),
            follow_redirects=True,
            headers={
                "user-agent": config.user_agent,
                "accept-language": "ru-RU,ru;q=0.9,en;q=0.8",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- низкий уровень ---

    async def _request(self, method: str, url: str, *, referer: str | None = None,
                       origin: str | None = None, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        if referer:
            headers["referer"] = referer
        if origin:
            headers["origin"] = origin
        if self.store.is_configured:
            headers["cookie"] = self.store.cookie_header()
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                return await self._client.request(method, url, headers=headers, **kwargs)
            except httpx.HTTPError as exc:  # сеть/таймаут
                last_error = exc
                if attempt < self.config.retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise errors.upstream_unavailable(last_error)

    async def _ajax(self, path: str, action: str, params: dict[str, Any] | None = None,
                    *, referer: str | None = None, origin: str | None = None,
                    retry_auth: bool = True) -> Envelope:
        body = {k: v for k, v in (params or {}).items() if v is not None}
        body["action"] = action
        data = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v))
                for k, v in body.items()}
        started = asyncio.get_event_loop().time()
        response = await self._request(
            "POST", path, data=data,
            headers={
                "accept": "application/json, text/javascript, */*; q=0.01",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "x-requested-with": "XMLHttpRequest",
                "pragma": "no-cache",
            },
            referer=referer, origin=origin,
        )
        envelope = parse(response.text)
        logger.debug("ajax", extra={"action": action, "status": envelope.status,
                                    "duration_ms": int((asyncio.get_event_loop().time() - started) * 1000)})
        if envelope.denied or ACCESS_DENIED in response.text.lower():
            if not retry_auth:
                raise errors.TobizError(errors.ACCESS_DENIED, "Конструктор отклонил запрос",
                                        "Сессия недействительна, и релогин отключён")
            await self.login(force=True)
            return await self._ajax(path, action, params, referer=referer, origin=origin,
                                    retry_auth=False)
        return envelope

    # --- публичный API клиента ---

    async def panel_ajax(self, action: str, **params: Any) -> Envelope:
        return await self._ajax(ep.PANEL_AJAX, action, params,
                                referer=f"{self.config.base_url}/projects/",
                                origin=self.config.base_url)

    async def editor_ajax(self, action: str, lp_base: str, page_id: str,
                          **params: Any) -> Envelope:
        return await self._ajax(ep.EDITOR_AJAX, action, params,
                                referer=self.config.editor_url(self._project_of(lp_base), page_id),
                                origin=lp_base)

    @staticmethod
    def _project_of(lp_base: str) -> str:
        match = re.match(r"https?://([0-9]+)\.", lp_base or "")
        return match.group(1) if match else ""

    async def fetch_text(self, url: str, *, referer: str | None = None) -> str:
        response = await self._request("GET", url, referer=referer,
                                       headers={"accept": "text/html,application/xhtml+xml"})
        return response.text

    async def fetch_bytes(self, url: str) -> bytes:
        response = await self._request("GET", url, headers={"accept": "*/*"})
        return response.content

    async def upload_image(self, file_name: str, content: bytes, content_type: str,
                           block_id: str, lp_base: str, page_id: str,
                           project_id: str) -> dict[str, Any]:
        files = {"image": (file_name, content, content_type)}
        data = {"block_id": str(block_id)}
        response = await self._request(
            "POST", ep.EDITOR_UPLOAD, data=data, files=files,
            headers={"x-requested-with": "XMLHttpRequest",
                     "accept": "application/json, text/javascript, */*; q=0.01"},
            referer=self.config.editor_url(project_id, page_id), origin=lp_base,
        )
        envelope = parse(response.text)
        result = dict(envelope.payload)
        result.setdefault("status", envelope.status)
        if envelope.denied:
            raise errors.TobizError(errors.AUTH_LOST, "Конструктор отклонил загрузку (нет доступа)",
                                    "Проверьте сессию: tobiz_login")
        status = str(result.get("status", "")).lower()
        if status == "ok" and result.get("image"):
            return result
        raise errors.TobizError(
            errors.UPLOAD_REJECTED,
            str(result.get("msg") or response.text[:300] or "Конструктор отклонил файл"),
            "Частые причины: не передан или неверен block_id (конструктор отвечает "
            "«Изображение не загружено! #2»), неподходящий формат/размер файла. "
            "Самый частый случай — неверный block_id страницы",
            raw=result,
        )

    # --- сессия ---

    async def ensure_session(self) -> None:
        if self.store.is_configured and not self.store.needs_verify:
            return
        if self.store.is_configured:
            probe = await self._ajax(ep.PANEL_AJAX, ep.PANEL_AJAX_ACTION_PROJECTS,
                                     referer=f"{self.config.base_url}/projects/",
                                     origin=self.config.base_url, retry_auth=False)
            if probe.ok:
                self.store.mark_verified()
                self.store.save()
                return
            if not self.config.has_credentials:
                raise errors.TobizError(
                    errors.ACCESS_DENIED,
                    "Сохранённая сессия не подтвердилась, а TOBIZ_EMAIL/TOBIZ_PASSWORD не заданы",
                    "Обновите cookies.json в томе сессии (достаточно пар session и email) "
                    "или задайте креды в devops/.env",
                )
        await self.login(force=True)

    async def login(self, force: bool = False) -> dict[str, Any]:
        async with self._lock:
            if not force and self.store.is_configured and self.store.verified_at:
                return self.store.describe()
            if not self.config.has_credentials:
                raise errors.TobizError(
                    errors.AUTH_FAILED, "Не заданы TOBIZ_EMAIL и TOBIZ_PASSWORD",
                    "Заполните devops/.env и перезапустите контейнер",
                )
            self._login_attempts += 1
            try:
                await self._client.get(ep.LOGIN_PATH, headers={"accept": "text/html"})
            except httpx.HTTPError as exc:
                raise errors.upstream_unavailable(exc)
            response = await self._request(
                "POST", ep.LOGIN_PATH,
                data={"email": self.config.email, "password": self.config.password},
                headers={"content-type": "application/x-www-form-urlencoded",
                         "accept": "text/html,application/xhtml+xml"},
                referer=f"{self.config.base_url}{ep.LOGIN_PATH}",
                origin=self.config.base_url,
            )
            jar = {cookie.name: cookie.value for cookie in self._client.cookies.jar
                   if cookie.value is not None}
            page = (response.text or "").lower()
            if "hcaptcha" in page:
                self.store.clear()
                raise errors.auth_captcha()
            if not jar.get("session") or not jar.get("email"):
                self.store.clear()
                raise errors.auth_failed()
            self.store.update_from_client(jar)
            probe = await self._ajax(ep.PANEL_AJAX, ep.PANEL_AJAX_ACTION_PROJECTS,
                                     referer=f"{self.config.base_url}/projects/",
                                     origin=self.config.base_url, retry_auth=False)
            if not probe.ok:
                self.store.clear()
                raise errors.auth_failed()
            self.store.mark_verified()
            self.store.save()
            logger.info("сессия получена", extra={"status": probe.status})
            return self.store.describe()

    def describe_session(self) -> dict[str, Any]:
        return self.store.describe()
