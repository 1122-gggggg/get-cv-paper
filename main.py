"""FastAPI app: arXiv dashboard backend.

Composition only — no business logic. Cache lives in cache.py, upstream
adapters in clients.py, discipline map in disciplines.py.
"""
from __future__ import annotations

import asyncio
import html as _html
import json as _json
import logging
import os
import re
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from cache import CachedJSON, LRUStore, etag_response, make_etag
from clients import (
    ARXIV_UA,
    fetch_arxiv_listing,
    fetch_arxiv_search,
    fetch_biorxiv_listing,
    fetch_crossref_listing,
    fetch_dblp_venues_many,
    fetch_hf_daily,
    fetch_openalex_listing,
    fetch_openreview_listing,
    fetch_pubmed_listing,
    fetch_pwc_many,
    fetch_s2_author_papers,
    fetch_s2_author_search,
    fetch_s2_batch,
    fetch_s2_recommendations,
    fetch_s2_search,
    s2_fos_for_cat,
)
from dedup import merge_sources
from disciplines import DEFAULT_DISCIPLINE, DISCIPLINES, discipline
from paper_store import PaperStore
from semantic import HF_EMBED_MODEL, HF_TOKEN, cache_stats as semantic_cache_stats, semantic_rank

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.environ.get("CACHE_DIR", ".cache"))
CACHE_DIR.mkdir(exist_ok=True)


# ── HTTP client 單例 ─────────────────────────────────────────────
_http_client: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        # http2: 多源 RTT 重用同 socket(httpx 透過 h2 套件提供)
        # 連線池拉滿:warmup 4 disc + 用戶並行,峰值 30+ 連線
        try:
            _http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={"User-Agent": ARXIV_UA},
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=40),
                http2=True,
                follow_redirects=True,
            )
        except ImportError:
            # h2 沒裝就降回 http/1.1
            logger.warning("h2 not installed, falling back to HTTP/1.1")
            _http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={"User-Agent": ARXIV_UA},
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=40),
                http2=False,
                follow_redirects=True,
            )
    return _http_client


# ── 快取 ─────────────────────────────────────────────────────────
# Endpoint SWR:fresh ttl 內直接回;stale 內回舊資料 + 背景刷新;完全過期才等。
# Server-side stale 6h,讓使用者永遠 < 50ms,刷新成本攤到背景。
_papers_cache = CachedJSON(ttl=10 * 60, stale_ttl=6 * 3600, max_keys=64)
_trending_cache = CachedJSON(ttl=30 * 60, stale_ttl=24 * 3600, max_keys=8)

# 個別 ID-level 快取(citations / pwc):跨 request 共享、JSON 持久化
_s2_store = LRUStore("s2", maxsize=20000, ttl=6 * 3600, cache_dir=CACHE_DIR)
_pwc_store = LRUStore("pwc", maxsize=20000, ttl=24 * 3600, cache_dir=CACHE_DIR)

# L2 持久化論文庫:跨容器重啟保留近 N 天熱門論文,upstream 429 時降級供應
_paper_store = PaperStore(CACHE_DIR / "papers.sqlite")
_PAPER_STORE_RETENTION_DAYS = 100
_PAPER_STORE_CLEANUP_INTERVAL = 6 * 3600

# Warmup:啟動立刻跑 + 每 5 分鐘背景刷新熱門 disciplines。
# 注意:max 必須與 script.js 實際請求對齊(/api/papers?max_results=50),否則 cache key 不同,
# 首位使用者仍要付冷啟動成本。
_WARMUP_DISCIPLINES = ("cv", "ml", "ai", "nlp")
_WARMUP_DAYS = 7
_WARMUP_MAX = 50
_WARMUP_INTERVAL = 5 * 60
_WARMUP_CONCURRENCY = 2  # arXiv 嚴格限流;同時 ≤2 路請求避免 429

_PAPERS_MAX_RESULTS = 5000
_PAPERS_DAYS_MAX = 90
_TRENDING_DAYS_MAX = 30
_SEARCH_MAX_RESULTS = 100
_CITATIONS_MAX = 200
_PWC_IDS_MAX = 100
_OPENREVIEW_DAYS_MAX = 365
_OPENREVIEW_MAX_RESULTS = 1000
_BIBTEX_IDS_MAX = 50


def _bounded_int(
    value: int | str | None,
    *,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    try:
        n = int(value) if value is not None else default
    except (TypeError, ValueError):
        n = default
    return max(min_value, min(max_value, n))


def _unique_csv(raw: str, *, max_items: int, field_name: str = "ids") -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in raw.split(","):
        item = item.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) > max_items:
            raise HTTPException(status_code=400, detail=f"too many {field_name} (max {max_items})")
    return out


async def _flush_task() -> None:
    while True:
        try:
            await asyncio.sleep(60)
            for s in (_s2_store, _pwc_store):
                s.flush()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("flush task error: %s", e)
            await asyncio.sleep(60)


async def _paper_cleanup_task() -> None:
    """每 6 小時刪除 retention 視窗外的 L2 論文,控制 SQLite 大小。"""
    await asyncio.sleep(30)
    while True:
        try:
            await asyncio.to_thread(_paper_store.cleanup, _PAPER_STORE_RETENTION_DAYS)
            await asyncio.sleep(_PAPER_STORE_CLEANUP_INTERVAL)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("paper cleanup task error: %s", e)
            await asyncio.sleep(_PAPER_STORE_CLEANUP_INTERVAL)


async def _warmup_loop() -> None:
    """背景預熱:啟動後等 5 秒讓 server ready,然後每 _WARMUP_INTERVAL 跑一輪。

    每輪對 _WARMUP_DISCIPLINES 各觸發一次 papers 預熱,寫進 _papers_cache。
    使用者首次打開直接 < 50ms 命中。Semaphore 控制 ≤ _WARMUP_CONCURRENCY 並發,
    避免一次性對 arXiv 砸 4 個請求被 429。
    """
    await asyncio.sleep(5)
    sem = asyncio.Semaphore(_WARMUP_CONCURRENCY)

    async def _warm_one(disc_id: str) -> None:
        async with sem:
            try:
                key, builder = _papers_build_spec(disc_id, _WARMUP_DAYS, _WARMUP_MAX)
                await _papers_cache.warm(key, builder)
            except Exception as e:
                logger.warning("warmup %s failed: %s", disc_id, e)

    while True:
        try:
            await asyncio.gather(*[_warm_one(d) for d in _WARMUP_DISCIPLINES])
            try:
                await _trending_cache.warm("hf_daily:7", _trending_build_spec(7))
            except Exception as e:
                logger.warning("warmup trending failed: %s", e)
            await asyncio.sleep(_WARMUP_INTERVAL)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # 任何漏網 exception 都不要讓整個 task 死掉,讓 SWR 繼續運作
            logger.warning("warmup loop error: %s", e)
            await asyncio.sleep(_WARMUP_INTERVAL)


_INDEX_HTML: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _INDEX_HTML
    try:
        _INDEX_HTML = Path("static/index.html").read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("index.html load failed: %s", e)
    flush = asyncio.create_task(_flush_task())
    warm = asyncio.create_task(_warmup_loop())
    cleanup = asyncio.create_task(_paper_cleanup_task())
    try:
        yield
    finally:
        flush.cancel()
        warm.cancel()
        cleanup.cancel()
        for s in (_s2_store, _pwc_store):
            s.flush()
        _paper_store.close()
        if _http_client is not None:
            await _http_client.aclose()


app = FastAPI(lifespan=lifespan)
# Brotli 比 gzip 省 ~15-25% bytes;沒裝就降回 gzip
try:
    from brotli_asgi import BrotliMiddleware
    app.add_middleware(BrotliMiddleware, minimum_size=1000, quality=4)
except ImportError:
    logger.info("brotli-asgi not installed, using gzip")
    app.add_middleware(GZipMiddleware, minimum_size=1000)


# ── Static long-cache + security headers ─────────────────────────
class HeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/"):
            if path.endswith("/sw.js"):
                response.headers["Cache-Control"] = "no-cache"
            elif path.endswith((".woff2", ".woff", ".ttf", ".png", ".jpg", ".webp")):
                response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
            elif path.endswith("/disciplines.js"):
                response.headers["Cache-Control"] = "public, max-age=604800, must-revalidate"
            elif path.endswith((".css", ".js", ".svg")):
                response.headers["Cache-Control"] = "public, max-age=300, must-revalidate"
            else:
                response.headers["Cache-Control"] = "public, max-age=86400"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        # CSP: 唯一 inline script 是 index.html 的 JSON-LD,以 sha256 hash 放行;
        # style-src 保留 unsafe-inline (CSS-in-JS 與 :focus outline 樣式有 inline 需求)
        if not response.headers.get("Content-Security-Policy"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'sha256-rp6QQ0ouE7tj2BbEMIflchpTVG+LQoePo1NY8ph7K0w=' https://accounts.google.com https://apis.google.com; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "img-src 'self' data: https:; "
                "connect-src 'self' https://accounts.google.com; "
                "frame-src https://accounts.google.com; "
                "font-src 'self' data: https://fonts.gstatic.com; "
                "base-uri 'self'; form-action 'self'"
            )
        return response


# ── 簡易 IP token bucket(免外部依賴,防濫用)────────────────────
class RateLimitMiddleware(BaseHTTPMiddleware):
    """每 IP per-minute token bucket。寫入 user data 算高成本,GET 一律 cost=1。"""

    def __init__(self, app, burst: int = 600):
        super().__init__(app)
        self.burst = burst
        self._buckets: dict[str, deque] = {}
        self._last_sweep = time.time()

    def _sweep_idle(self, now: float) -> None:
        """每 5 分鐘清掉 1 分鐘窗外完全沒活動的 IP,防止 DoS 撐爆 dict。"""
        if now - self._last_sweep < 300:
            return
        self._last_sweep = now
        window = 60.0
        dead = [ip for ip, dq in self._buckets.items() if not dq or now - dq[-1] > window]
        for ip in dead:
            self._buckets.pop(ip, None)

    def _client_ip(self, request: Request) -> str:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/") or path == "/api/health":
            return await call_next(request)

        ip = self._client_ip(request)
        now = time.time()
        self._sweep_idle(now)
        window = 60.0
        dq = self._buckets.setdefault(ip, deque())
        while dq and now - dq[0] > window:
            dq.popleft()

        cost = 3 if (request.method == "PUT" and path == "/api/me/data") else 1
        if len(dq) + cost > self.burst:
            return Response(
                content=_json.dumps({"detail": "rate limited"}),
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "10"},
            )

        response = await call_next(request)
        if response.status_code < 500:
            for _ in range(cost):
                dq.append(now)
        return response


app.add_middleware(RateLimitMiddleware)
app.add_middleware(HeadersMiddleware)

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── routes ───────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"ok": True, "t": int(time.time())}


def _ssr_compact(p: dict) -> dict:
    return {
        "url": p.get("url"),
        "title": (p.get("title") or "")[:260],
        "summary": (p.get("summary") or "")[:280],
        "authors": p.get("authors") or [],
        "published": p.get("published"),
        "venue": p.get("venue"),
        "github_url": p.get("github_url"),
    }


@app.get("/")
async def read_root():
    html_doc = _INDEX_HTML
    if not html_doc:
        return FileResponse("static/index.html")
    try:
        key, _builder = _papers_build_spec(DEFAULT_DISCIPLINE, _WARMUP_DAYS, _WARMUP_MAX)
        ent = _papers_cache._get_entry(key)
        if ent is not None:
            _at, body, _etag = ent
            data = _json.loads(body)
            papers = (data.get("papers") or [])[:12]
            if papers:
                compact = [_ssr_compact(p) for p in papers]
                safe = _html.escape(_json.dumps(compact, ensure_ascii=False), quote=True)
                island = (
                    f'<div id="ssr-papers" hidden '
                    f'data-disc="{DEFAULT_DISCIPLINE}" data-json="{safe}"></div>'
                )
                html_doc = html_doc.replace("</body>", island + "</body>", 1)
    except Exception as e:
        logger.warning("SSR injection failed: %s", e)
    return HTMLResponse(
        content=html_doc,
        headers={"Cache-Control": "public, max-age=60, must-revalidate"},
    )


@app.get("/sw.js")
def sw_root():
    # Service Worker 以根路徑作用域註冊
    return FileResponse(
        "static/sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/robots.txt")
def robots_txt():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Sitemap: /sitemap.xml\n"
    )
    return Response(content=body, media_type="text/plain")


@app.get("/sitemap.xml")
def sitemap_xml():
    # 列出每個 discipline 的根頁面 (CSR with query),讓爬蟲至少知道存在
    urls = ['<url><loc>/</loc><changefreq>hourly</changefreq><priority>1.0</priority></url>']
    for did in DISCIPLINES.keys():
        urls.append(f'<url><loc>/?discipline={did}</loc><changefreq>daily</changefreq><priority>0.7</priority></url>')
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) +
        "\n</urlset>\n"
    )
    return Response(content=body, media_type="application/xml")


def _papers_build_spec(discipline_id: str, days: int, max_results: int):
    """回傳 (cache_key, builder coroutine factory) — 給 endpoint 與 warmup 共用。"""
    days = _bounded_int(days, default=7, min_value=1, max_value=_PAPERS_DAYS_MAX)
    max_results = _bounded_int(
        max_results,
        default=1000,
        min_value=1,
        max_value=_PAPERS_MAX_RESULTS,
    )
    if days >= 30 and max_results < 5000:
        max_results = 5000
    disc = discipline(discipline_id)
    arxiv_native = bool(disc.get("arxiv_native", True))
    openalex_concept = disc.get("openalex_concept")
    crossref_subject = disc.get("crossref_subject")
    pubmed_mesh = disc.get("pubmed_mesh")
    use_biorxiv = bool(disc.get("biorxiv"))
    use_medrxiv = bool(disc.get("medrxiv"))
    cache_key = (
        f"{disc.get('cat','')}:{openalex_concept or ''}:{crossref_subject or ''}:"
        f"{pubmed_mesh or ''}:{int(use_biorxiv)}:{int(use_medrxiv)}:"
        f"{int(arxiv_native)}:{days}:{max_results}"
    )

    arxiv_max = max_results if arxiv_native else min(max_results, 200)
    openalex_max = 0 if arxiv_native and not openalex_concept else min(max_results, 300)
    crossref_max = 0 if arxiv_native and not crossref_subject else min(max_results, 200)
    biorxiv_max = min(max_results, 150) if use_biorxiv else 0
    medrxiv_max = min(max_results, 150) if use_medrxiv else 0
    pubmed_max = min(max_results, 200) if pubmed_mesh else 0
    # S2 search 作為 arXiv 限流時的補強:只對 arxiv_native 領域開啟
    s2_max = min(max_results, 100) if arxiv_native else 0

    async def build():
        c = _client()

        async def _safe(name: str, coro):
            try:
                return await coro
            except Exception as e:
                logger.warning("%s listing failed for %s: %s", name, discipline_id, e)
                return []

        tasks = [_safe("arxiv", fetch_arxiv_listing(c, disc["cat"], days, arxiv_max))]
        if s2_max > 0:
            s2_query = disc.get("name") or disc.get("cat") or ""
            tasks.append(_safe("s2", fetch_s2_search(
                c, query=s2_query, fos=s2_fos_for_cat(disc.get("cat", "")),
                days=days, max_results=s2_max,
            )))
        if openalex_max > 0:
            tasks.append(_safe("openalex", fetch_openalex_listing(
                c, concept_id=openalex_concept, days=days, max_results=openalex_max,
                search_query=None if openalex_concept else disc.get("name"),
            )))
        if crossref_max > 0:
            tasks.append(_safe("crossref", fetch_crossref_listing(
                c, subject=crossref_subject, days=days, max_results=crossref_max,
                search_query=None if crossref_subject else disc.get("name"),
            )))
        if biorxiv_max > 0:
            tasks.append(_safe("biorxiv", fetch_biorxiv_listing(c, "biorxiv", days, biorxiv_max)))
        if medrxiv_max > 0:
            tasks.append(_safe("medrxiv", fetch_biorxiv_listing(c, "medrxiv", days, medrxiv_max)))
        if pubmed_max > 0:
            tasks.append(_safe("pubmed", fetch_pubmed_listing(c, pubmed_mesh, days, pubmed_max)))

        sources = await asyncio.gather(*tasks)
        merged = merge_sources(*sources)

        primary_cat = disc.get("cat") or ""
        if merged and primary_cat:
            try:
                await asyncio.to_thread(_paper_store.upsert_many, merged, primary_cat)
            except Exception as e:
                logger.warning("paper_store upsert failed for %s: %s", discipline_id, e)

        if not merged:
            # L2 fallback: upstream 全掛時,改從 SQLite 撈最近 days 內的歷史紀錄
            if primary_cat:
                try:
                    l2 = await asyncio.to_thread(
                        _paper_store.query, primary_cat, days, max_results
                    )
                except Exception as e:
                    logger.warning("paper_store query failed for %s: %s", discipline_id, e)
                    l2 = []
                if l2:
                    logger.info("L2 fallback for %s: %d papers", discipline_id, len(l2))
                    return {
                        "papers": l2[:500],
                        "arxiv_native": arxiv_native,
                        "from_l2": True,
                    }
            raise RuntimeError(f"all sources empty for {discipline_id}")
        if len(merged) > 500:
            merged = merged[:500]
        return {"papers": merged, "arxiv_native": arxiv_native}

    return cache_key, build


def _trending_build_spec(days: int):
    async def build():
        return {"papers": await fetch_hf_daily(_client(), days), "source": "hf_daily"}
    return build


@app.get("/api/papers")
async def get_papers(
    request: Request,
    max_results: int = 1000,
    days: int = 7,
    discipline_id: str = Query(DEFAULT_DISCIPLINE, alias="discipline"),
):
    days = _bounded_int(days, default=7, min_value=1, max_value=_PAPERS_DAYS_MAX)
    max_results = _bounded_int(
        max_results,
        default=1000,
        min_value=1,
        max_value=_PAPERS_MAX_RESULTS,
    )
    cache_key, builder = _papers_build_spec(discipline_id, days, max_results)
    body, etag = await _papers_cache.get_or_build(cache_key, builder)
    return etag_response(request, body, etag)


@app.get("/api/trending")
async def get_trending(request: Request, source: str = "hf_daily", days: int = 7):
    if source != "hf_daily":
        raise HTTPException(status_code=400, detail=f"unknown source: {source}")
    days = _bounded_int(days, default=7, min_value=1, max_value=_TRENDING_DAYS_MAX)
    cache_key = f"{source}:{days}"
    body, etag = await _trending_cache.get_or_build(cache_key, _trending_build_spec(days))
    return etag_response(request, body, etag)


@app.get("/api/search")
async def search_papers(q: str, max_results: int = 50):
    query = q.strip()
    if not query:
        return {"papers": []}
    max_results = _bounded_int(
        max_results,
        default=50,
        min_value=1,
        max_value=_SEARCH_MAX_RESULTS,
    )
    return {"papers": await fetch_arxiv_search(_client(), query, max_results)}


async def _papers_for_discipline(discipline_id: str) -> list[dict]:
    """Reuse the warmup cache key so we never hit arXiv with a large fresh build."""
    cache_key, builder = _papers_build_spec(discipline_id, _WARMUP_DAYS, _WARMUP_MAX)
    body, _etag = await _papers_cache.get_or_build(cache_key, builder)
    payload = _json.loads(body)
    return payload.get("papers") or []


@app.get("/api/semantic-search")
async def semantic_search(
    q: str,
    discipline_id: str = Query(DEFAULT_DISCIPLINE, alias="discipline"),
    top_k: int = 30,
    cross: bool = False,
):
    """Cosine top-k over HF-embedded paper pool. Reuses warmup cache to avoid arXiv 429.

    `cross=true` (or `discipline=all`) pools warmup disciplines for interdisciplinary search.
    """
    query = q.strip()
    if not query:
        return {"papers": [], "query": "", "model": HF_EMBED_MODEL}
    if not HF_TOKEN:
        raise HTTPException(status_code=503, detail="semantic search unavailable (HF_TOKEN missing)")

    top_k = _bounded_int(top_k, default=30, min_value=1, max_value=100)

    if cross or discipline_id == "all":
        pools = await asyncio.gather(*[
            _papers_for_discipline(d) for d in _WARMUP_DISCIPLINES
        ], return_exceptions=True)
        papers: list[dict] = []
        seen: set[str] = set()
        for pool in pools:
            if isinstance(pool, Exception):
                continue
            for p in pool:
                k = p.get("id") or p.get("doi") or p.get("link") or p.get("title", "")
                if k and k not in seen:
                    seen.add(k)
                    papers.append(p)
        used_disc = "all"
    else:
        try:
            papers = await _papers_for_discipline(discipline_id)
        except Exception as e:
            logger.warning("semantic-search: paper pool unavailable for %s: %s", discipline_id, e)
            raise HTTPException(status_code=503, detail=f"paper pool unavailable: {e}") from e
        used_disc = discipline_id

    if len(papers) > 400:
        papers = papers[:400]

    try:
        ranked = await semantic_rank(_client(), query, papers, top_k=top_k)
    except Exception as e:
        logger.warning("semantic_rank failed: %s", e)
        raise HTTPException(status_code=502, detail=f"embedding failure: {e}") from e

    return {
        "papers": ranked,
        "query": query,
        "discipline": used_disc,
        "model": HF_EMBED_MODEL,
        "pool_size": len(papers),
    }


@app.get("/api/disciplines")
def list_disciplines():
    return {
        "disciplines": [{"id": k, **v} for k, v in DISCIPLINES.items()],
        "default": DEFAULT_DISCIPLINE,
    }


# ── Semantic Scholar citation proxy ──────────────────────────────
# GET 版:支援 service worker / browser HTTP cache (POST 不能)。
@app.get("/api/citations")
async def get_citations(
    request: Request,
    arxiv_ids: str = Query("", description="comma-separated arXiv IDs"),
    titles: str = Query("", description="JSON {arxiv_id: title} 用於 DBLP fallback"),
):
    ids = _unique_csv(arxiv_ids, max_items=_CITATIONS_MAX, field_name="ids")
    if not ids:
        return {"results": {}}

    titles_map: dict[str, str] = {}
    if titles:
        try:
            parsed = _json.loads(titles)
            if isinstance(parsed, dict):
                titles_map = {
                    str(k): str(v)[:240]
                    for k, v in parsed.items()
                    if str(k) in ids
                }
        except Exception:
            pass

    result: dict[str, dict] = {}
    missing: list[str] = []
    for aid in ids:
        cached = _s2_store.get(aid)
        if cached is not None:
            result[aid] = cached
        else:
            missing.append(aid)

    if missing:
        fresh = await fetch_s2_batch(_client(), missing)
        for aid, entry in fresh.items():
            _s2_store.set(aid, entry)
            result[aid] = entry

    # DBLP venue fallback: S2 沒給 venue 的論文,用 title 反查 DBLP (CS 會議補強)
    if titles_map:
        need_venue: dict[str, str] = {}
        for aid, entry in result.items():
            if not entry.get("venue") and titles_map.get(aid):
                need_venue[titles_map[aid]] = aid
        if need_venue:
            try:
                venues = await fetch_dblp_venues_many(_client(), list(need_venue.keys()))
                for title, venue in venues.items():
                    aid = need_venue.get(title)
                    if aid and venue:
                        result[aid] = {**result[aid], "venue": venue}
                        _s2_store.set(aid, result[aid])
            except Exception as e:
                logger.warning("DBLP venue fallback failed: %s", e)

    body = _json.dumps({"results": result}, ensure_ascii=False).encode("utf-8")
    etag = make_etag(body)
    return etag_response(request, body, etag)


# ── Papers with Code proxy ───────────────────────────────────────
@app.get("/api/pwc")
async def get_pwc(request: Request, arxiv_ids: str):
    ids = _unique_csv(arxiv_ids, max_items=_PWC_IDS_MAX, field_name="ids")
    missing = [a for a in ids if _pwc_store.get(a) is None]
    if missing:
        fresh = await fetch_pwc_many(_client(), missing, concurrency=5)
        for aid, entry in fresh.items():
            _pwc_store.set(aid, entry)

    out: dict[str, dict] = {}
    for a in ids:
        v = _pwc_store.get(a)
        if v:
            out[a] = {"github_url": v.get("github_url"), "stars": v.get("stars", 0)}

    body = _json.dumps({"results": out}, ensure_ascii=False).encode("utf-8")
    etag = make_etag(body)
    return etag_response(request, body, etag)


# ── Cache + RL observability ─────────────────────────────────────
_METRICS_KEY = os.environ.get("METRICS_KEY", "")


@app.get("/api/metrics")
def get_metrics(key: str = ""):
    """供 dashboard / 自我觀測用。設定 METRICS_KEY 環境變數後需帶 ?key=..."""
    if _METRICS_KEY and key != _METRICS_KEY:
        raise HTTPException(status_code=403, detail="forbidden")
    return {
        "papers_cache": _papers_cache.stats(),
        "trending_cache": _trending_cache.stats(),
        "s2_store": {"entries": len(_s2_store._data)},
        "pwc_store": {"entries": len(_pwc_store._data)},
        "semantic_cache": semantic_cache_stats(),
        "paper_store": _paper_store.stats(),
    }


# ── OpenReview (ICLR / NeurIPS / ICML 投稿 + 評審) ────────────────
_OPENREVIEW_VENUES = {"iclr", "neurips", "icml", "colm"}
_openreview_cache = CachedJSON(ttl=30 * 60, stale_ttl=24 * 3600, max_keys=32)


@app.get("/api/openreview")
async def get_openreview(
    request: Request,
    venue: str = Query("iclr"),
    year: int | None = None,
    days: int = 30,
    max_results: int = 200,
):
    venue = venue.lower()
    if venue not in _OPENREVIEW_VENUES:
        raise HTTPException(
            status_code=400, detail=f"unknown venue: {venue}; expected one of {_OPENREVIEW_VENUES}"
        )
    days = _bounded_int(days, default=30, min_value=1, max_value=_OPENREVIEW_DAYS_MAX)
    max_results = _bounded_int(
        max_results,
        default=200,
        min_value=1,
        max_value=_OPENREVIEW_MAX_RESULTS,
    )
    if year is not None:
        year = _bounded_int(
            year,
            default=time.gmtime().tm_year,
            min_value=2013,
            max_value=time.gmtime().tm_year + 1,
        )
    cache_key = f"{venue}:{year or 'auto'}:{days}:{max_results}"

    async def build():
        return {
            "papers": await fetch_openreview_listing(
                _client(), venue, year=year, days=days, max_results=max_results,
            ),
            "venue": venue,
            "year": year,
        }

    body, etag = await _openreview_cache.get_or_build(cache_key, build)
    return etag_response(request, body, etag)


# ── 相似論文推薦 (Semantic Scholar) ─────────────────────────────
_recs_cache = CachedJSON(ttl=2 * 3600, stale_ttl=24 * 3600, max_keys=128)


@app.get("/api/recommendations")
async def get_recommendations(
    request: Request,
    arxiv_id: str = Query(..., min_length=4),
    limit: int = 10,
):
    arxiv_id = arxiv_id.strip()
    if not arxiv_id:
        raise HTTPException(status_code=400, detail="missing arxiv_id")
    limit = _bounded_int(limit, default=10, min_value=1, max_value=50)
    cache_key = f"{arxiv_id}:{limit}"

    async def build():
        return {
            "seed": arxiv_id,
            "papers": await fetch_s2_recommendations(_client(), arxiv_id, limit=limit),
        }

    body, etag = await _recs_cache.get_or_build(cache_key, build)
    return etag_response(request, body, etag)


# ── 作者搜尋 / 作者論文 (S2) ────────────────────────────────────
_author_search_cache = CachedJSON(ttl=24 * 3600, stale_ttl=7 * 24 * 3600, max_keys=256)
_author_papers_cache = CachedJSON(ttl=2 * 3600, stale_ttl=24 * 3600, max_keys=128)


@app.get("/api/author/search")
async def author_search(request: Request, q: str = Query(..., min_length=2), limit: int = 5):
    name = q.strip()
    if not name:
        return {"authors": []}
    limit = _bounded_int(limit, default=5, min_value=1, max_value=20)
    cache_key = f"{name.lower()}:{limit}"

    async def build():
        return {"authors": await fetch_s2_author_search(_client(), name, limit=limit)}

    body, etag = await _author_search_cache.get_or_build(cache_key, build)
    return etag_response(request, body, etag)


@app.get("/api/author/{author_id}/papers")
async def author_papers(request: Request, author_id: str, limit: int = 50):
    author_id = author_id.strip()
    if not author_id or not author_id.isdigit():
        raise HTTPException(status_code=400, detail="invalid author_id")
    limit = _bounded_int(limit, default=50, min_value=1, max_value=100)
    cache_key = f"{author_id}:{limit}"

    async def build():
        return {
            "author_id": author_id,
            "papers": await fetch_s2_author_papers(_client(), author_id, limit=limit),
        }

    body, etag = await _author_papers_cache.get_or_build(cache_key, build)
    return etag_response(request, body, etag)


# ── BibTeX export (取代被刪掉的 import/export) ────────────────────
_BIBTEX_KEY_RE = re.compile(r"[^A-Za-z0-9]+")


def _bibtex_key(authors: list[str], year: str, title: str) -> str:
    last = ""
    if authors:
        parts = authors[0].split()
        if parts:
            last = parts[-1].lower()
    last = _BIBTEX_KEY_RE.sub("", last) or "anon"
    yr = (year[:4] if year else "")
    first_word = ""
    for w in title.split():
        cleaned = _BIBTEX_KEY_RE.sub("", w).lower()
        if cleaned and cleaned not in {"a", "an", "the", "on", "of", "in", "for"}:
            first_word = cleaned
            break
    return f"{last}{yr}{first_word}"[:50] or "ref"


# LaTeX 特殊字元: & % $ # _ { } ~ ^ \  → 編譯會壞,逐字 escape
_BIBTEX_ESCAPE_MAP = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _bibtex_escape(s: str) -> str:
    out = []
    for ch in s:
        out.append(_BIBTEX_ESCAPE_MAP.get(ch, ch))
    return "".join(out).strip()


@app.get("/api/bibtex")
async def export_bibtex(arxiv_ids: str = Query(...)):
    ids_raw = _unique_csv(arxiv_ids, max_items=_BIBTEX_IDS_MAX, field_name="ids")
    if not ids_raw:
        raise HTTPException(status_code=400, detail="missing arxiv_ids")
    # 用 S2 取 metadata (含 venue / year);沒命中就只給 arXiv 樣板
    fresh: dict[str, dict] = {}
    missing = [a for a in ids_raw if _s2_store.get(a) is None]
    if missing:
        fresh = await fetch_s2_batch(_client(), missing)
        for aid, entry in fresh.items():
            _s2_store.set(aid, entry)

    out: list[str] = []
    for aid in ids_raw:
        meta = _s2_store.get(aid) or {}
        venue = meta.get("venue") or ""
        # arXiv ID 形如 2401.12345; year 可從 ID 前綴推 (年/月)
        year = ""
        m = re.match(r"(\d{2})(\d{2})\.", aid)
        if m:
            year = "20" + m.group(1)
        title = meta.get("title") or aid
        authors = meta.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        key = _bibtex_key(authors, year, title)
        author_str = " and ".join(_bibtex_escape(a) for a in authors) if authors else ""
        entry_lines = [f"@article{{{key},"]
        entry_lines.append(f"  title = {{{_bibtex_escape(title)}}},")
        if author_str:
            entry_lines.append(f"  author = {{{author_str}}},")
        if year:
            entry_lines.append(f"  year = {{{year}}},")
        if venue:
            entry_lines.append(f"  journal = {{{_bibtex_escape(venue)}}},")
        entry_lines.append(f"  eprint = {{{aid}}},")
        entry_lines.append("  archivePrefix = {arXiv},")
        entry_lines.append(f"  url = {{https://arxiv.org/abs/{aid}}}")
        entry_lines.append("}")
        out.append("\n".join(entry_lines))

    body = "\n\n".join(out) + "\n"
    return Response(
        content=body,
        media_type="application/x-bibtex; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="papers.bib"'},
    )
