"""Внутренние эндпоинты конструктора — единственное место с их именами."""

from __future__ import annotations

# Панель: список проектов вместе со списком страниц (HTML в поле html)
PANEL_AJAX = "/system/ajax.php"
PANEL_AJAX_ACTION_PROJECTS = "get_projects"

# Редактор: всё, что связано со страницей и блоками
EDITOR_AJAX = "/system/editor/ajax.php"
EDITOR_UPLOAD = "/system/editor/upload.php"

# Действия редактора (проверены на живом аккаунте)
ACT_GET_BLOCKS = "GetBlocks"
ACT_CREATE_BLOCK = "CreateNewBlock"
ACT_SAVE_BLOCKS = "SaveBlocks"
ACT_SECTION_GROUPS = "GetSectionGroups"
ACT_RANDOM_SECTION = "GetRandomSectionByGroupId"
ACT_DEFAULT_VALUES = "fetchSectionDefaultValues"
ACT_HEADER_IDS = "GetHeaderIDs"
ACT_REFRESH_EDIT_TIME = "refreshPageEditoTime"

# Вход
LOGIN_PATH = "/login/"

# Публичные ресурсы lp-домена
LP_BLOCKS_JS = "/js/blocks2.js"
LP_CATALOG = "/json/sections.json"
LP_STYLE_PRESETS = "/json/stylesFontsPresets.json"

# Бандлы вендора, из которых рендерер берёт хелперы и шаблоны
LP_VENDOR_BUNDLES = (
    "/js/underscore-min.js",
    "/js/blocks2.js",
    "/js/editor.min.js",
    "/js/editor/min/editor.bundle.min.js",
    "/js/script.min.js",
    "/js/tools/flex_tools.min.js",
)
