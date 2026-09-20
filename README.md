# tobiz-mcp

MCP-сервер для конструктора сайтов **TOBIZ**: даёт агенту (Hermes, Codex, OpenCode и любому
MCP-клиенту) читать и менять сайты — проекты, страницы, блоки, изображения.

## Быстрый старт

```bash
git clone git@github.com:raydev-ru/tobiz-mcp.git && cd tobiz-mcp
cp .env.example .env                 # вписать TOBIZ_EMAIL и TOBIZ_PASSWORD
docker build -t tobiz-mcp .
```

Проверка, что сервер видит конструктор (логин/сессия и рендерер):

```bash
docker run --rm --entrypoint tobiz-mcp-selftest --env-file .env \
  -v tobiz-session:/data/session -v tobiz-assets:/data/assets \
  tobiz-mcp --health
```

Ожидаемый ответ — JSON, где `session.present: true` и `renderer_available: true`. Если логин по
паролю аккаунт не пропускает (встречается капча), положите свою сессию в том — см.
«Полезно знать» ниже.

Дальше достаточно подключить сервер к своему агенту — он запускает образ сам, как stdio-сервер.

## Подключение к агенту

Подставьте свой абсолютный путь к `.env`. Образ запускается с `-i` (stdio) — больше ничего не нужно.

**Hermes**

```bash
hermes mcp add tobiz --command docker --args run -i --rm \
  --env-file /путь/до/tobiz-mcp2/.env \
  -v tobiz-session:/data/session -v tobiz-assets:/data/assets \
  tobiz-mcp
hermes mcp test tobiz
```

**Codex** (`~/.codex/config.toml`)

```toml
[mcp_servers.tobiz]
command = "docker"
args = ["run", "-i", "--rm", "--env-file", "/путь/до/tobiz-mcp2/.env",
        "-v", "tobiz-session:/data/session", "-v", "tobiz-assets:/data/assets", "tobiz-mcp"]
startup_timeout_sec = 30
tool_timeout_sec = 180
```

**OpenCode** (`opencode.json`)

```json
{"mcp": {"servers": {"tobiz": {"type": "local",
  "command": ["docker", "run", "-i", "--rm", "--env-file", "/путь/до/tobiz-mcp2/.env",
              "-v", "tobiz-session:/data/session", "-v", "tobiz-assets:/data/assets", "tobiz-mcp"]}}}}
```

Инструменты появятся с префиксом сервера — например `mcp__tobiz__tobiz_list_projects`.

Загрузка картинок работает через файлы: положите изображение в локальный каталог и смонтируйте
его как `/data/inbox`, тогда путь к файлу передаётся в `tobiz_upload_image` (либо сразу
`content_base64`, без монтирования).

## Два режима работы

MCP — это JSON-RPC, а не REST, и клиент подключается к серверу одним из двух способов:

| | **stdio** (по умолчанию) | **HTTP** (streamable HTTP) |
| --- | --- | --- |
| Кто запускает контейнер | клиент-агент сам: `docker run -i --rm …` | вы, один раз: `docker run -d …` |
| Сколько контейнеров | один на сессию агента, живёт до её конца | один постоянный, обслуживает всех |
| Кому подходит | Hermes / Codex / OpenCode на этой машине | клиенты по сети, несколько агентов, отладка через curl |
| Черновик правок | свой у каждого агента | общий на всех клиентов |

Контейнер запускается **не на каждую команду**: он один на сессию, а вызовы инструментов идут в него
потоком JSON-RPC (в stdio — через stdin/stdout). Черновик правок и кеш библиотеки блоков живут в
процессе, cookie-сессия — на томе, поэтому переживает перезапуск контейнера.

Постоянный HTTP-сервис:

```bash
docker run -d --name tobiz-mcp --restart unless-stopped -p 8765:8765 \
  -e MCP_TRANSPORT=http -e MCP_HTTP_TOKEN=секрет --env-file .env \
  -v tobiz-session:/data/session -v tobiz-assets:/data/assets tobiz-mcp
# endpoint: http://<хост>:8765/mcp, заголовок Authorization: Bearer секрет
```

Цена общего сервиса: черновик один на процесс — несколько агентов на одной странице будут мешать
друг другу. Для параллельной работы удобнее stdio: у каждого агента свой контейнер и свой черновик.

## Инструкции для агента (скил)

Инструменты — половина дела: агенту нужно знать порядок работы, грабли вендора и как проверять
результат. Это лежит в скиле [`skills/tobiz-mcp/SKILL.md`](skills/tobiz-mcp/SKILL.md).

**Hermes** — скил лежит в репозитории, вместе со справочниками (каталог блоков, движок, компоненты,
эндпоинты). Копируй папку целиком:

```bash
git clone https://github.com/raydev-ru/tobiz-mcp.git /tmp/tobiz-mcp
cp -r /tmp/tobiz-mcp/skills/tobiz-mcp ~/.hermes/skills/
```

Установка по прямой ссылке (`hermes skills install <raw-URL на SKILL.md>`) тоже работает, но
приносит только `SKILL.md` — без справочников и рецептов.

**Codex / OpenCode** читают [`AGENTS.md`](AGENTS.md) из корня репозитория автоматически; если
работаете не из репозитория — скопируйте файл в свой конфиг (`~/.codex/AGENTS.md` и аналоги).

В скиле: что пишется сразу, а что только по `tobiz_save_page`; 15 проверенных грабель (радиус
кнопок в `em` и вендорский CSS 2px, автоконтраст текста в формах, обязательный `block_id` при
загрузке картинок, отстающий `window.tobiz`, `?v=` = id страницы) и короткие рецепты под типовые
задачи.

## Инструменты

| Инструмент | Что делает |
| --- | --- |
| `tobiz_login`, `tobiz_session_status`, `tobiz_health` | вход, состояние сессии, диагностика |
| `tobiz_list_projects` | проекты (сайты) аккаунта |
| `tobiz_list_pages` | страницы проекта |
| `tobiz_page_summary` | компактная карта страницы: порядок блоков, короткий текст, SEO-подсказка |
| `tobiz_list_blocks`, `tobiz_get_block` | блоки страницы и значения полей блока |
| `tobiz_page_info` | параметры страницы как в панели: название, URL, SEO, og:image, доступ |
| `tobiz_search_blocks`, `tobiz_describe_block` | поиск по библиотеке блоков, схема полей типа |
| `tobiz_add_block`, `tobiz_update_block`, `tobiz_delete_block`, `tobiz_move_block` | правки черновика |
| `tobiz_save_page` | запись блоков на сайт: рендер HTML, SaveBlocks, проверка вёрстки |
| `tobiz_update_page` | правка параметров страницы (SEO, название, slug, og:image) — пишет сразу |
| `tobiz_copy_page` | копия страницы вместе с блоками в тот же или другой проект |
| `tobiz_delete_page` | удаление страницы (требует `confirm=true`) |
| `tobiz_discard_changes`, `tobiz_verify_page` | откат черновика, проверка публичной вёрстки |
| `tobiz_upload_image`, `tobiz_set_block_image` | загрузка изображения и подстановка в поле |
| `tobiz_refresh_assets` | перекачать библиотеку блоков проекта |

Ответ инструмента: `{"ok": true, "data": {...}}` либо
`{"ok": false, "error": {"code": "...", "message": "...", "hint": "..."}}`.

## Как это устроено (коротко)

Редактор TOBIZ хранит не «значения полей», а готовый HTML блока, поэтому сервер рендерит этот HTML
сам — Node с шаблонами и хелперами вендора внутри образа. Правки **блоков** копятся в черновике в
памяти сервера и уходят на сайт только по явному `tobiz_save_page`.

Параметры самой страницы (название, URL, SEO, картинка для соцсетей) живут не в черновике, а в
панели конструктора: `tobiz_update_page` читает форму страницы, подменяет указанные поля и
отправляет её целиком — такое изменение видно на сайте сразу. Копирование и удаление страницы
(`tobiz_copy_page`, `tobiz_delete_page`) тоже применяются немедленно.

## Полезно знать

* **Блоки** не меняются без `tobiz_save_page`; `tobiz_update_page`, `tobiz_copy_page` и
  `tobiz_delete_page` пишут на сайт сразу — проверяйте `project_id`/`page_id` перед вызовом.
* `tobiz_update_page` отправляет всю форму страницы (как редактор), поэтому не переданные поля
  сохраняются как были — SEO можно править, не затирая название и slug.
* `tobiz_delete_page` требует `confirm=true`: без него вернётся отказ с названием страницы.
* Для экспериментов заведите отдельный сайт и `TOBIZ_READ_ONLY=1`.
* Если аккаунт требует капчу при входе, сервис вернёт `AUTH_CAPTCHA`. Тогда положите свою сессию
  в том — хватит двух cookie `session` и `email`:

  ```bash
  # cookies.json = {"session": "...", "email": "..."}
  docker run --rm -u 0 --entrypoint sh -v tobiz-session:/data -v "$PWD:/seed:ro" \
    tobiz-mcp -c 'cp /seed/cookies.json /data/session/ && chown -R 10001:10001 /data/session'
  ```

  После этого `TOBIZ_EMAIL`/`TOBIZ_PASSWORD` в `.env` можно оставить пустыми.
* `tobiz_upload_image` требует `block_id` реального блока страницы (без него конструктор отвечает
  «Изображение не загружено! #2»).
* Секреты не логируются: в журнал попадают только имена cookie.

## Переменные окружения

| Переменная | Назначение |
| --- | --- |
| `TOBIZ_EMAIL`, `TOBIZ_PASSWORD` | вход в конструктор (не нужны, если положена сессия) |
| `TOBIZ_READ_ONLY` | `1` — только чтение, инструменты правки не регистрируются |
| `TOBIZ_ALLOWED_PROJECT_IDS` | CSV со списком разрешённых `project_id`; пусто — все проекты аккаунта |
| `TOBIZ_MAX_UPLOAD_MB` | лимит файла изображения (по умолчанию 10) |
| `MCP_TRANSPORT` | `stdio` (по умолчанию) или `http` |
| `MCP_HTTP_PORT`, `MCP_HTTP_TOKEN` | порт и токен для HTTP-транспорта |
| `TOBIZ_LOG_LEVEL` | `INFO` по умолчанию, `WARNING` — тише |
