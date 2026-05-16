# ── Stage 1: minify static assets via esbuild ───────────────────
FROM node:20-alpine AS minifier
WORKDIR /work
COPY static ./static
RUN npm install -g --no-audit --no-fund esbuild@0.24.2 >/dev/null && \
    for f in script.js disciplines.js value-metrics.js sw.js; do \
        if [ -f "static/$f" ]; then \
            esbuild "static/$f" --minify --target=es2020 --legal-comments=none > "static/$f.min" && \
            mv "static/$f.min" "static/$f"; \
        fi; \
    done && \
    for f in style.css washi.css; do \
        if [ -f "static/$f" ]; then \
            esbuild "static/$f" --minify --loader=css > "static/$f.min" && \
            mv "static/$f.min" "static/$f"; \
        fi; \
    done && \
    ls -la static/

# ── Stage 2: runtime ───────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# 用 minified 版本覆蓋 static/(來源檔不變,production 載入更快)
COPY --from=minifier /work/static ./static

RUN mkdir -p /data && chown -R 1000:1000 /data
ENV CACHE_DIR=/data
USER 1000:1000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
