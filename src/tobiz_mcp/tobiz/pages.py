"""Разбор HTML-ответа панели: проекты (сайты) и их страницы.

Эндпоинта списка страниц у конструктора нет — и проекты, и страницы приходят в разметке
`action=get_projects` (отдельного эндпоинта у конструктора нет). Здесь единственное место, зависящее от
этой разметки; менять его надо только вместе с фикстурой tests/contract/fixtures/get_projects.html.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any

from ..errors import NOT_FOUND, PAGES_PARSE_FAILED, TobizError

_PROJECT_SPLIT = re.compile(r'<div class="project"\s+data-id="(\d+)"')
_VERSION_RE = re.compile(r'<div class="version ([^"]*)">(.*?)(?=<div class="version |\Z)', re.S)
_PAGE_ID_RE = re.compile(r'class="page_id">\s*(\d+)\s*<')
_PAGE_TITLE_RE = re.compile(
    r'class="page_title">\s*<a\s+href="([^"]+)"[^>]*title="([^"]*)"[^>]*>(.*?)</a>', re.S)
_EDIT_RE = re.compile(r'<a[^>]*href="([^"]*?v=\d+&(?:amp;)?editor=true)"[^>]*class="edit_page', re.S)
_EDIT_RE_ALT = re.compile(r'class="edit_page btn small"\s*>', re.S)
_TITLE_RE = re.compile(r'class="project_title">(.*?)</div>', re.S)
_DESCR_RE = re.compile(r'class="project_descr">(.*?)</div>', re.S)
_SITE_RE = re.compile(r'class="site_link"[^>]*href="([^"]+)"')
_SLUG_RE = re.compile(r"^https?://[^/]+/([^/?]+)/?$")


@dataclass
class Page:
    page_id: str
    title: str = ""
    url: str = ""
    slug: str = ""
    visible: bool = True
    editor_relative: str = ""

    def editor_url(self, lp_template: str, project_id: str) -> str:
        base = lp_template.format(project_id=project_id)
        return f"{base}/?v={self.page_id}&editor=true"

    def to_dict(self, lp_template: str | None = None, project_id: str = "") -> dict[str, Any]:
        data: dict[str, Any] = {
            "page_id": self.page_id,
            "title": self.title,
            "slug": self.slug,
            "url": self.url,
            "visible": self.visible,
        }
        if lp_template and project_id:
            data["editor_url"] = self.editor_url(lp_template, project_id)
        return data


@dataclass
class Project:
    project_id: str
    title: str = ""
    description: str = ""
    site_url: str = ""
    has_domain: bool = False
    pages: list[Page] = field(default_factory=list)

    def to_dict(self, lp_template: str | None = None, include_pages: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "project_id": self.project_id,
            "title": self.title,
            "description": self.description,
            "site_url": self.site_url,
            "has_domain": self.has_domain,
            "pages_count": len(self.pages),
        }
        if lp_template:
            data["editor_url"] = f"{lp_template.format(project_id=self.project_id)}/?editor=true"
        if include_pages:
            data["pages"] = [p.to_dict(lp_template, self.project_id) for p in self.pages]
        return data


def _clean(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def parse_projects(html_body: str, lp_template: str = "") -> list[Project]:
    """Разбирает HTML панели в список проектов со страницами."""
    if not html_body or '<div class="project"' not in html_body:
        raise TobizError(
            PAGES_PARSE_FAILED,
            "В ответе конструктора нет списка проектов",
            "Разметка панели изменилась: обновите разбор в tobi z/pages.py и фикстуру теста",
        )
    marks = list(_PROJECT_SPLIT.finditer(html_body))
    projects: list[Project] = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(html_body)
        chunk = html_body[mark.start():end]
        project = Project(project_id=mark.group(1))
        title = _TITLE_RE.search(chunk)
        descr = _DESCR_RE.search(chunk)
        site = _SITE_RE.search(chunk)
        project.title = _clean(title.group(1)) if title else ""
        project.description = _clean(descr.group(1)) if descr else ""
        project.site_url = site.group(1) if site else ""
        project.has_domain = 'class="add_domain"' not in chunk

        for version in _VERSION_RE.finditer(chunk):
            classes, body = version.group(1), version.group(2)
            page_id = _PAGE_ID_RE.search(body)
            if not page_id:
                continue
            link = _PAGE_TITLE_RE.search(body)
            page = Page(page_id=page_id.group(1))
            if link:
                page.url = html.unescape(link.group(1))
                page.title = html.unescape(link.group(2) or "").strip() or _clean(link.group(3))
                if not page.title:
                    page.title = _clean(link.group(3))
                slug = _SLUG_RE.match(page.url)
                if slug:
                    page.slug = slug.group(1)
            # скрытая страница помечена иконкой fa-eye-slash (см. фикстуру get_projects.html)
            page.visible = "fa-eye-slash" not in body
            project.pages.append(page)
        projects.append(project)
    return [p for p in projects if p.project_id]


def page_or_raise(projects: list[Project], page_id: str) -> tuple[Project, Page]:
    for project in projects:
        for page in project.pages:
            if page.page_id == str(page_id):
                return project, page
    raise TobizError(
        NOT_FOUND,
        f"Страница {page_id} не найдена среди страниц аккаунта",
        "Вызовите tobiz_list_pages и используйте page_id из ответа",
    )


# --- форма правки страницы (action=edit_page_form) ---
#
# Панель отдаёт готовый HTML формы: параметры страницы (название, slug, SEO, доступ по паролю,
# картинка для соцсетей). Значения этих полей — источник правды: `window.tobiz` в редакторе
# может отставать, а edit_page принимает полный набор полей, поэтому его надо отправить целиком.

_TAG_RE = re.compile(r"<(input|textarea)\b([^>]*)>(?:(.*?)</textarea>)?", re.I | re.S)
_ATTR_RE = re.compile(r"([\w:.-]+)\s*=\s*\"([^\"]*)\"", re.S)
_CHECKED_RE = re.compile(r"(?<![\w-])checked(?![\w-])", re.I)
_SELECTED_RE = re.compile(r"(?<![\w-])selected(?![\w-])", re.I)
_SELECT_RE = re.compile(r"<select\b([^>]*)>(.*?)</select>", re.I | re.S)
_OPTION_RE = re.compile(r"<option\b([^>]*)>(.*?)(?=<option|\Z)", re.I | re.S)

#: поля формы, имеющие смысл для агента (остальные — служебные)
PAGE_FORM_TEXT_FIELDS = (
    "page_title", "page_dir", "page_seo_title", "page_seo_keywords",
    "page_seo_description", "page_valid_login", "page_valid_password", "page_image",
)
PAGE_FORM_CHECKBOX_FIELDS = ("page_user_personal_seo_configs", "page_access_control")


@dataclass
class PageForm:
    """Разобранная форма панели (edit_page, copy_page_to_anp)."""

    text: dict[str, str] = field(default_factory=dict)        # name -> value
    checked: dict[str, str] = field(default_factory=dict)     # name -> value (чекбокс отмечен)
    options: dict[str, list[str]] = field(default_factory=dict)  # radio -> варианты
    selects: dict[str, list[dict[str, str]]] = field(default_factory=dict)  # select -> варианты
    html: str = ""

    @property
    def fields(self) -> dict[str, str]:
        """Полный набор полей для отправки: текст + отмеченные чекбоксы."""
        return {**self.text, **self.checked}

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            key: self.text.get(key, "") for key in PAGE_FORM_TEXT_FIELDS if key in self.text
        }
        for key in PAGE_FORM_CHECKBOX_FIELDS:
            data[key] = key in self.checked
        if "page_image" in self.options:
            data["page_image_options"] = self.options["page_image"]
        if self.selects:
            data["selects"] = self.selects
        return data


def _parse_selects(html_body: str, form: PageForm) -> None:
    """Достаёт <select> с вариантами (в форме копирования так выбирают проект)."""
    for attrs, body in _SELECT_RE.findall(html_body):
        attributes = {name.lower(): value for name, value in _ATTR_RE.findall(attrs)}
        name = attributes.get("name") or attributes.get("id")
        if not name:
            continue
        variants: list[dict[str, str]] = []
        for option_attrs, option_body in _OPTION_RE.findall(body):
            option_values = {k.lower(): v for k, v in _ATTR_RE.findall(option_attrs)}
            title = html.unescape(re.sub(r"<[^>]+>", "", option_body or "")).strip()
            variants.append({"value": option_values.get("value", ""), "title": title,
                             "selected": "1" if _SELECTED_RE.search(option_attrs) else "0"})
        if variants:
            form.selects[name] = variants


def parse_edit_form(html_body: str) -> PageForm:
    """Разбирает HTML формы панели в структуру. Терпим к порядку атрибутов."""
    if not html_body or "<form" not in html_body.lower():
        raise TobizError(
            PAGES_PARSE_FAILED,
            "В ответе конструктора нет формы",
            "Проверьте action=edit_page_form / copy_page_to_anp_form и обновите to biz/pages.py",
        )
    form = PageForm(html=html_body)
    for tag, attrs, content in _TAG_RE.findall(html_body):
        attributes = {name.lower(): value for name, value in _ATTR_RE.findall(attrs)}
        name = attributes.get("name")
        if not name:
            continue
        kind = (attributes.get("type") or tag).lower()
        if tag.lower() == "textarea":
            form.text[name] = html.unescape(re.sub(r"<[^>]+>", "", content or "")).strip()
            continue
        value = attributes.get("value", "")
        if kind == "checkbox":
            if _CHECKED_RE.search(attrs):
                form.checked[name] = value or "1"
            continue
        if kind == "radio":
            form.options.setdefault(name, []).append(value)
            if _CHECKED_RE.search(attrs):
                form.text[name] = value
            continue
        if kind in ("submit", "button", "reset", "file"):
            continue
        form.text[name] = value
    _parse_selects(html_body, form)
    return form
