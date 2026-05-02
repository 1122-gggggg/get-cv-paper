"""FastAPI app: arXiv dashboard backend.

Composition only — no business logic. Cache lives in cache.py, upstream
adapters in clients.py, auth + user data in userdata.py, discipline map
in disciplines.py.
"""
from __future__ import annotations

import asyncio
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
from fastapi.responses import FileResponse, Response
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
)
from dedup import merge_sources
from disciplines import DEFAULT_DISCIPLINE, DISCIPLINES, discipline
from userdata import router as userdata_router

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

# Warmup:啟動立刻跑 + 每 5 分鐘背景刷新熱門 disciplines(命中率最高的 4 個 + 預設 7d/1000)
_WARMUP_DISCIPLINES = ("cv", "ml", "ai", "nlp")
_WARMUP_DAYS = 7
_WARMUP_MAX = 1000
_WARMUP_INTERVAL = 5 * 60


async def _flush_task() -> None:
    while True:
        await asyncio.sleep(60)
        for s in (_s2_store, _pwc_store):
            s.flush()


async def _warmup_loop() -> None:
    """背景預熱:啟動後等 5 秒讓 server ready,然後每 _WARMUP_INTERVAL 跑一輪。

    每輪對 _WARMUP_DISCIPLINES 各觸發一次 papers 預熱,寫進 _papers_cache。
    使用者首次打開直接 < 50ms 命中。
    """
    await asyncio.sleep(5)
    while True:
        for disc_id in _WARMUP_DISCIPLINES:
            try:
                key, builder = _papers_build_spec(disc_id, _WARMUP_DAYS, _WARMUP_MAX)
                await _papers_cache.warm(key, builder)
            except Exception as e:
                logger.warning("warmup %s failed: %s", disc_id, e)
        try:
            await _trending_cache.warm("hf_daily:7", _trending_build_spec(7))
        except Exception as e:
            logger.warning("warmup trending failed: %s", e)
        await asyncio.sleep(_WARMUP_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    flush = asyncio.create_task(_flush_task())
    warm = asyncio.create_task(_warmup_loop())
    try:
        yield
    finally:
        flush.cancel()
        warm.cancel()
        for s in (_s2_store, _pwc_store):
            s.flush()
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
        # CSP: 允許 inline script (Google Sign-In), self origin, 第三方 logo/img;
        # connect-src 包含所有上游 API 來源 (S2/PWC/OpenAlex/etc 不直連前端,所以只允許 self)
        if not response.headers.get("Content-Security-Policy"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://accounts.google.com https://apis.google.com; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "connect-src 'self' https://accounts.google.com; "
                "frame-src https://accounts.google.com; "
                "font-src 'self' data:; "
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
app.include_router(userdata_router)


# ── routes ───────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"ok": True, "t": int(time.time())}


@app.get("/")
def read_root():
    return FileResponse("static/index.html")


@app.get("/sw.js")
def sw_root():
    # Service Worker 以根路徑作用域註冊
    return FileResponse(
        "static/sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


def _papers_build_spec(discipline_id: str, days: int, max_results: int):
    """回傳 (cache_key, builder coroutine factory) — 給 endpoint 與 warmup 共用。"""
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

    async def build():
        c = _client()

        async def _safe(name: str, coro):
            try:
                return await coro
            except Exception as e:
                logger.warning("%s listing failed for %s: %s", name, discipline_id, e)
                return []

        tasks = [_safe("arxiv", fetch_arxiv_listing(c, disc["cat"], days, arxiv_max))]
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
        # stale-on-error: 全部源都掛(merged 空)時 raise,讓 SWR 保留舊資料,
        # 而不是把 cache 寫成空白覆蓋掉好的歷史
        if not merged and any(len(s) == 0 for s in sources) and all(len(s) == 0 for s in sources):
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
    cache_key, builder = _papers_build_spec(discipline_id, days, max_results)
    body, etag = await _papers_cache.get_or_build(cache_key, builder)
    return etag_response(request, body, etag)


@app.get("/api/trending")
async def get_trending(request: Request, source: str = "hf_daily", days: int = 7):
    if source != "hf_daily":
        raise HTTPException(status_code=400, detail=f"unknown source: {source}")
    cache_key = f"{source}:{days}"
    body, etag = await _trending_cache.get_or_build(cache_key, _trending_build_spec(days))
    return etag_response(request, body, etag)


@app.get("/api/search")
async def search_papers(q: str, max_results: int = 50):
    if not q.strip():
        return {"papers": []}
    return {"papers": await fetch_arxiv_search(_client(), q, max_results)}


@app.get("/api/disciplines")
def list_disciplines():
    return {
        "disciplines": [{"id": k, **v} for k, v in DISCIPLINES.items()],
        "default": DEFAULT_DISCIPLINE,
    }


# ── Semantic Scholar citation proxy ──────────────────────────────
# GET 版:支援 service worker / browser HTTP cache (POST 不能)。
# arxiv_ids 用 comma-separated query param,上限 200 個避免 URL 過長 + S2 濫用。
_CITATIONS_MAX = 200


@app.get("/api/citations")
async def get_citations(
    request: Request,
    arxiv_ids: str = Query("", description="comma-separated arXiv IDs"),
    titles: str = Query("", description="JSON {arxiv_id: title} 用於 DBLP fallback"),
):
    ids_raw = [a.strip() for a in arxiv_ids.split(",") if a.strip()]
    if not ids_raw:
        return {"results": {}}
    if len(ids_raw) > _CITATIONS_MAX:
        raise HTTPException(status_code=400, detail=f"too many ids (max {_CITATIONS_MAX})")
    # 去重保序
    seen: set[str] = set()
    ids: list[str] = []
    for a in ids_raw:
        if a not in seen:
            seen.add(a)
            ids.append(a)

    titles_map: dict[str, str] = {}
    if titles:
        try:
            parsed = _json.loads(titles)
            if isinstance(parsed, dict):
                titles_map = {str(k): str(v) for k, v in parsed.items()}
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
    ids = [a.strip() for a in arxiv_ids.split(",") if a.strip()]
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
@app.get("/api/metrics")
def get_metrics():
    """供 dashboard / 自我觀測用,不對外公開敏感資料。"""
    return {
        "papers_cache": _papers_cache.stats(),
        "trending_cache": _trending_cache.stats(),
        "s2_store": {"entries": len(_s2_store._data)},
        "pwc_store": {"entries": len(_pwc_store._data)},
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
    limit = max(1, min(limit, 50))
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
    limit = max(1, min(limit, 20))
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
    limit = max(1, min(limit, 100))
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


def _bibtex_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("{", "").replace("}", "").strip()


@app.get("/api/bibtex")
async def export_bibtex(arxiv_ids: str = Query(...)):
    ids_raw = [a.strip() for a in arxiv_ids.split(",") if a.strip()][:50]
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
