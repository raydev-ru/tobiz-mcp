# syntax=docker/dockerfile:1
# tobiz-mcp: MCP-сервер + Node-рендерер блоков в одном образе.
# Node нужен только для рендера шаблонов вендора (рендер HTML блока шаблонами вендора).

FROM node:22.23.2-slim AS node

FROM python:3.12-slim-trixie

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NODE_PATH=/opt/renderer/node_modules

# Node из отдельного слоя (libstdc++ уже есть в slim-образе)
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Рендерер: jsdom — единственная npm-зависимость
COPY renderer ./renderer
RUN cd /app/renderer && npm install --omit=dev --no-audit --no-fund \
 && npm cache clean --force

# Непривилегированный пользователь; /data — тома (session, assets, inbox, audit)
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin tobiz \
 && mkdir -p /data/session /data/assets /data/inbox /data/audit \
 && chown -R tobiz:tobiz /data /app

USER tobiz

ENV TOBIZ_SESSION_DIR=/data/session \
    TOBIZ_ASSETS_DIR=/data/assets \
    TOBIZ_INBOX_DIR=/data/inbox \
    TOBIZ_AUDIT_DIR=/data/audit \
    TOBIZ_RENDERER_DIR=/app/renderer

HEALTHCHECK --interval=60s --timeout=25s --start-period=20s --retries=3 \
    CMD ["python", "-m", "tobiz_mcp.selftest", "--health"]

ENTRYPOINT ["python", "-m", "tobiz_mcp"]
