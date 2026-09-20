# Инструкции для агента: сайты TOBIZ через MCP

Этот репозиторий — MCP-сервер `tobiz-mcp` для конструктора сайтов TOBIZ. Агент подключается к нему
как к обычному MCP-серверу (stdio, образ `tobiz-mcp`) и получает 24 инструмента `tobiz_*`
(в Hermes они видны как `mcp__tobiz__*`).

Подробные правила, грабли и рецепты — в [`skills/tobiz-mcp/SKILL.md`](skills/tobiz-mcp/SKILL.md).
Ниже — самое важное, что нужно помнить, если скилы недоступны.

## Порядок работы

1. `tobiz_list_projects` → `tobiz_list_pages` → `tobiz_page_summary`.
2. Найти блок: `tobiz_search_blocks` → `tobiz_describe_block` (имена и подписи полей).
3. Правки блоков идут **в черновик**: `tobiz_add_block`, `tobiz_update_block`,
   `tobiz_delete_block`, `tobiz_move_block`.
4. Записать на сайт: `tobiz_save_page` (сервер сам рендерит HTML блоков шаблонами вендора).
5. Проверить: `tobiz_verify_page` по публичной вёрстке.

## Жёсткие правила

* **Блоки на сайте не меняются без `tobiz_save_page`.** Правки без сохранения живут только в
  памяти сервера.
* **`tobiz_update_page` (SEO, название, slug, og:image), `tobiz_copy_page`, `tobiz_delete_page`
  пишут сразу.** `delete_page` требует `confirm=true`.
* **Тип блока — параметр `type_id`** (не `block_type_id`), иначе `UNKNOWN_TYPE`.
* **`select`-поля — строкой** (`mode="3"`), **массивы (`arr1`, `form1`) — целиком**.
* **Перезаписывай демо-контент вендора** («Плиточные работы», «Тариф М», телефон `+7 800 333 22 33`),
  иначе он попадёт на сайт.
* **`tobiz_upload_image` требует `block_id` реального блока страницы** (#2 без него, #3 с чужим).
* **Текущие параметры страницы читай через `tobiz_page_info`** — ответ редактора может отставать.
* **Радиус кнопок — в `em`** (`radius: 0.389` при 17–18px ≈ 7px); у основных кнопок вендорский CSS
  ставит 2px, инлайн-радиус его перекрывает.
* **Цвет текста кнопок в формах полем не задаётся** — работает `var(--autocontrast-text-color)`:
  светлый фон → чёрный текст, тёмный → белый. Проверяй контраст вычисленным цветом.
* **`?v=<число>` в публичном URL — id страницы**; не подставляй туда свои значения.
* `status: OK` не значит «на сайте то, что нужно»: проверяй вёрстку (`tobiz_verify_page`), а для
  стилей — реальные стили в браузере (`getComputedStyle`; у скрытых попапов они тоже читаются).
* Для экспериментов — отдельный сайт и `TOBIZ_READ_ONLY=1`.

## Установка (кратко)

```bash
cp .env.example .env      # TOBIZ_EMAIL/TOBIZ_PASSWORD либо готовая сессия
docker build -t tobiz-mcp .
docker run --rm --entrypoint tobiz-mcp-selftest --env-file .env \
  -v tobiz-session:/data/session -v tobiz-assets:/data/assets tobiz-mcp --health
```

Подключение к клиентам (Hermes, Codex, OpenCode) — в [README.md](README.md), раздел
«Подключение к агенту».
