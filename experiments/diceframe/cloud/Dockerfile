# Build only the exported, patched upstream tree; never the local runtime data.
FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend-v2
COPY app/frontend-v2/package.json app/frontend-v2/package-lock.json ./
RUN npm ci
COPY app/frontend-v2/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRPG_WEB_HOST=0.0.0.0 \
    TRPG_WEB_PORT=9876 \
    TRPG_DATA_DIR=/app/data \
    TRPG_LOG_DIR=/app/data/logs \
    TRPG_INSTALL_MODE=docker \
    TZ=Asia/Hong_Kong
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates fonts-noto-cjk tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home diceframe \
    && mkdir /app/data \
    && chown diceframe:diceframe /app/data
COPY app/requirements-docker-amd64.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes --no-deps --only-binary=:all: \
    --platform manylinux_2_17_x86_64 --python-version 3.11 --implementation cp --abi cp311 \
    --target /opt/diceframe-dependencies -r /tmp/requirements.lock
RUN python -c "import site; from pathlib import Path; Path(site.getsitepackages()[0], 'diceframe.pth').write_text('/opt/diceframe-dependencies\n')"
COPY app/web_server.py ./
COPY app/src/ ./src/
COPY app/legal/ ./legal/
COPY app/prompts/ ./prompts/
COPY app/templates/ ./templates/
COPY app/plugins/ ./plugins/
COPY app/LICENSE release.json ./
COPY --from=frontend /build/static-v2/ ./static-v2/
USER 10001:10001
EXPOSE 9876
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:9876/api/system/update/health',timeout=3))['ok']"
CMD ["python", "web_server.py"]
