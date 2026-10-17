# ── Stage 1: minify static assets via esbuild ───────────────────
FROM node:20-alpine AS minifier
WORKDIR /work
COPY static ./static
RUN npm install -g --no-audit --no-fund esbuild@0.24.2 >/dev/null && \
    for f in app-utils.js script.js disciplines.js value-metrics.js sw.js; do \
        if [ -f "static/$f" ]; then \
            esbuild "static/$f" --minify --target=es2020 --legal-comments=none > "static/$f.min" && \
            mv "static/$f.min" "static/$f"; \
        fi; \
    done && \
    for f in style.css washi.css; do \
        if [ -f "static/$f" ]; then \
            esbuild "static/$f" --minify > "static/$f.min" && \
            mv "static/$f.min" "static/$f"; \
        fi; \
    done
RUN H=$(cat static/app-utils.js static/script.js static/style.css static/disciplines.js static/value-metrics.js | sha256sum | cut -c1-8) && \
    sed -i "s/const VERSION=[\"'][^\"']*[\"']/const VERSION='$H'/" static/sw.js

# ── Stage 2: runtime ───────────────────────────────────────────
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-compile -r requirements.txt

COPY cache.py clients.py dedup.py disciplines.py event_hub.py main.py oai_harvest.py paper_store.py semantic.py ./
COPY --from=minifier /work/static ./static

RUN mkdir -p /data && chown -R 1000:1000 /data
ENV CACHE_DIR=/data
USER 1000:1000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["sh", "-c", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT:-8000}/api/health', timeout=3).close()\""]

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
