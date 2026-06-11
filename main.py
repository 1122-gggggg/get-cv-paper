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
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from collections.abc import Callable

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders

from cache import CachedJSON, LRUStore, etag_response, make_etag
from clients import (
    ARXIV_UA,
    extract_github_url,
    fetch_arxiv_listing,
    fetch_arxiv_search,
    fetch_biorxiv_listing,
    fetch_chemrxiv_listing,
    fetch_crossref_listing,
    fetch_dblp_venues_many,
    fetch_github_stars,
    fetch_hf_daily,
    fetch_openalex_listing,
    fetch_openreview_listing,
    fetch_pubmed_listing,
    fetch_s2_author_papers,
    fetch_s2_author_search,
    fetch_s2_batch,
    fetch_s2_search,
    github_repo_slug,
    s2_fos_for_cat,
)
from dedup import merge_sources
from disciplines import DEFAULT_DISCIPLINE, DISCIPLINES, discipline
from event_hub import EventHub
from oai_harvest import harvest_arxiv_oai
from paper_store import PaperStore, _paper_id as _derive_paper_id
from semantic import (
    HF_EMBED_MODEL,
    HF_TOKEN,
    cache_stats as semantic_cache_stats,
    cluster_papers,
    hybrid_rank,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── 錯誤外送(Sentry / BetterStack)──────────────────────────────
# SENTRY_DSN 設了就啟用 Sentry;BETTERSTACK_TOKEN 設了就把 ERROR 級別 log 轉發到 BetterStack。
# 兩者都沒設就完全 no-op。模組缺也 no-op,不阻塞啟動。
class _BetterStackHandler(logging.Handler):
    """非同步把 ERROR 級別 log POST 到 BetterStack/Logtail。失敗就吞,避免 log 風暴。"""

    def __init__(self, token: str, endpoint: str = "https://in.logs.betterstack.com") -> None:
        super().__init__(level=logging.ERROR)
        self._token = token
        self._endpoint = endpoint
        self._sema = asyncio.Semaphore(4)  # 限 4 路並發,避免 burst 打死自家網絡
        # 跑 logging 時 event loop 可能還沒起;用 lazy client
        import httpx as _hx
        self._client = _hx.AsyncClient(timeout=5.0, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })

    async def _ship(self, payload: dict) -> None:
        async with self._sema:
            try:
                await self._client.post(self._endpoint, json=payload)
            except Exception:
                pass

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = {
                "dt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
            }
            if record.exc_info:
                payload["exception"] = logging.Formatter().formatException(record.exc_info)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._ship(payload))
            except RuntimeError:
                # 沒 loop(極早期 import 時)就丟棄,避免阻塞
                pass
        except Exception:
            pass


def _init_error_sinks() -> None:
    dsn = (os.environ.get("SENTRY_DSN") or "").strip()
    bs_token = (os.environ.get("BETTERSTACK_TOKEN") or "").strip()
    if dsn:
        try:
            import sentry_sdk  # type: ignore
            sentry_sdk.init(
                dsn=dsn,
                traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.0")),
                send_default_pii=False,
                environment=os.environ.get("APP_ENV", "prod"),
            )
            logger.info("error sink: Sentry initialized")
        except ImportError:
            logger.warning("SENTRY_DSN set but sentry-sdk not installed (pip install sentry-sdk)")
        except Exception as e:
            logger.warning("Sentry init failed: %s", e)
    if bs_token:
        try:
            h = _BetterStackHandler(bs_token, endpoint=os.environ.get("BETTERSTACK_ENDPOINT", "https://in.logs.betterstack.com"))
            h.setFormatter(logging.Formatter("%(name)s | %(message)s"))
            logging.getLogger().addHandler(h)
            logger.info("error sink: BetterStack handler attached")
        except Exception as e:
            logger.warning("BetterStack handler init failed: %s", e)


_init_error_sinks()

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
# 突發偵測:每 30 分新鮮、24h stale,讀 metric_snapshots delta(每日才變)
_emerging_cache = CachedJSON(ttl=30 * 60, stale_ttl=24 * 3600, max_keys=32)
_hot_cache = CachedJSON(ttl=15 * 60, stale_ttl=12 * 3600, max_keys=16)

# 個別 ID-level 快取(citations / pwc):跨 request 共享、JSON 持久化
_s2_store = LRUStore("s2", maxsize=20000, ttl=6 * 3600, cache_dir=CACHE_DIR)
_pwc_store = LRUStore("pwc", maxsize=20000, ttl=24 * 3600, cache_dir=CACHE_DIR)

# 動態子題聚類:每 30 分新鮮、24h stale,k-means 在 cached embedding 上跑(不打 HF)
_subtopics_cache = CachedJSON(ttl=30 * 60, stale_ttl=24 * 3600, max_keys=16)

# L2 持久化論文庫:跨容器重啟保留近 N 天熱門論文,upstream 429 時降級供應
_paper_store = PaperStore(CACHE_DIR / "papers.sqlite")
_PAPER_STORE_RETENTION_DAYS = 100
_PAPER_STORE_CLEANUP_INTERVAL = 6 * 3600

# Warmup:啟動立刻跑 + 每 5 分鐘背景刷新熱門 disciplines。
# cache key 對齊改由 _canonical_max() 處理:使用者 50 與 _WARMUP_MAX 80 都收斂到 80 桶,
# 不再依賴手動把常數對齊到 script.js。
# 主層(常駐, 5 分鐘輪詢):首頁最熱 4 個領域,使用者體感命中率最高
_WARMUP_DISCIPLINES = ("cv", "ml", "ai", "nlp")
# 次層(輪詢, 15 分鐘):覆蓋第二梯隊熱門領域,提高跨領域命中率
_WARMUP_DISCIPLINES_TIER2 = ("robotics", "graphics", "ir", "security", "systems", "hci")
_WARMUP_DAYS = 7
_WARMUP_MAX = 80  # 召回池:單領域 ~80,跨 4 領域 union ~320(>300 召回目標)
_WARMUP_INTERVAL = 5 * 60
_WARMUP_INTERVAL_TIER2 = 15 * 60
_WARMUP_CONCURRENCY = 2  # arXiv 嚴格限流;同時 ≤2 路請求避免 429

_PAPERS_MAX_RESULTS = 5000
_PAPERS_DAYS_MAX = 90
_PAPERS_RESPONSE_CAP = 500  # 單次 /api/papers 回傳上限(截斷前先全域排序)
# 召回層級:使用者請求(50)與語意召回(_WARMUP_MAX=80)都落入 80 桶,
# cache key 因此一致 → warmup 命中,首位使用者不再付冷啟動成本。
_CANONICAL_MAX_BUCKETS = (80, 200, 500, 1000, 5000)
_TRENDING_DAYS_MAX = 30
_SEARCH_MAX_RESULTS = 100
_SEMANTIC_POOL_MAX = 500  # 混合召回(BM25+dense)單次評分的候選上限
_EMERGING_WINDOW_MAX = 30
_EMERGING_LIMIT = 40
# Poisson-style burst 評分:delta / sqrt(baseline + prior)。prior 當平滑常數,
# 讓 0→5 的新秀(z≈1.79)勝過 100→105 的老牌(z≈0.49)。
_EMERGE_CIT_PRIOR = 5.0
_EMERGE_HF_PRIOR = 3.0
_EMERGE_STAR_PRIOR = 20.0  # star 數量級較大,prior 也較高,避免 0→30 爆分
_EMERGE_HF_WEIGHT = 0.6   # 引用是較持久的訊號,權重高於 HF 投票
_EMERGE_STAR_WEIGHT = 0.4  # GitHub star 是工程關注度,權重低於引用/HF
_EMERGE_MIN = 1.0         # z-score 門檻,過濾 50→51 這類噪音
# 全領域熱榜(/api/hot):跨所有 snapshot 追蹤的領域聚合 emergence,回答
# 「大家正在關注哪些領域/論文」。同一篇可橫跨多領域 → 取最高分、累積領域標籤。
_HOT_DISCIPLINES = _WARMUP_DISCIPLINES + _WARMUP_DISCIPLINES_TIER2
_HOT_DEFAULT_LIMIT = 40
_HOT_LIMIT_MAX = 100
_HOT_WINDOW_MAX = 30
_CITATIONS_MAX = 200
_PWC_IDS_MAX = 100
_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")  # 有 token → 5000 req/hr,無 → 60
# 背景 star 補值:對熱門領域近期論文解析 GitHub repo → 取 star → 寫進 snapshots。
# 無 token 時 GitHub 限 60 req/hr,故每輪上限壓低、間隔拉長以免被限流。
_STARS_INTERVAL = 30 * 60
_STARS_MAX_REPOS = 300 if _GITHUB_TOKEN else 40
# 評審熱度(/api/reviews):聚合 ICLR/NeurIPS/ICML/COLM 當年+前一年的投稿,
# 過濾出已有評審分數者,依 review_avg 排序 → 前端「評審熱度」視圖。
# 會議投稿在審查期不掛 arXiv id(雙盲),故無法併進主 feed,獨立視圖呈現。
_REVIEWS_VENUES = ("iclr", "neurips", "icml", "colm")
_REVIEWS_CYCLE_DAYS = 3650  # 內部呼叫抓整個年度投稿,不受 endpoint 365 上限
_REVIEWS_PER_VENUE = 1000
_REVIEWS_LIMIT = 300        # 聚合後回傳上限
_OPENREVIEW_DAYS_MAX = 365
_OPENREVIEW_MAX_RESULTS = 1000
_BIBTEX_IDS_MAX = 50
# 熱門度(/api/popular):匿名開啟次數的滾動視窗排行,/api/view beacon 累計。
_POPULAR_DAYS_MAX = 30
_POPULAR_LIMIT_MAX = 100
_VIEW_URL_MAX = 600        # beacon url 長度上限,過濾異常負載
_VIEW_TITLE_MAX = 400


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


# arXiv id 形態:新式 2401.12345(v2),或舊式 cs.AI/0601001(v1)
_ARXIV_ID_VALID_RE = re.compile(
    r"^(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z][a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)$"
)


def _valid_arxiv_ids(ids: list[str]) -> list[str]:
    """過濾成合法 arXiv id;擋掉亂填的字串浪費 embedding / 上游呼叫。"""
    return [i for i in ids if _ARXIV_ID_VALID_RE.match(i)]


# OAI-PMH 增量收割:Atom query API 單次有上限,高流量 archive(cs)會漏掉新論文;
# OAI ListRecords 以 resumption token 回傳完整窗口 → top-up L2 store,讓近期覆蓋齊全。
# free-tier VM 受限:預設僅收割 cs(密度最高、漏最多),每輪上限 max_pages × ~1000。
_OAI_ENABLED = os.environ.get("OAI_HARVEST_ENABLED", "1") != "0"
_OAI_SETS = tuple(
    s.strip() for s in os.environ.get("OAI_HARVEST_SETS", "cs").split(",") if s.strip()
)
_OAI_INTERVAL = _bounded_int(
    os.environ.get("OAI_HARVEST_INTERVAL_S"), default=6 * 3600, min_value=900, max_value=86400
)
_OAI_MAX_PAGES = _bounded_int(
    os.environ.get("OAI_HARVEST_MAX_PAGES"), default=4, min_value=1, max_value=50
)
_OAI_MAX_RECORDS = _bounded_int(
    os.environ.get("OAI_HARVEST_MAX_RECORDS"), default=4000, min_value=100, max_value=50000
)
_OAI_COLD_START_DAYS = 2  # 無 state 時的回溯窗口(天)


def _build_oai_cat_map() -> dict[str, set[str]]:
    """arXiv category → 應 upsert 的 primary_cat 集合(對齊 warmup 的 per-discipline 存法)。

    discipline d 想要 categories 與其 {cat}∪cats 相交的論文,存到 d['cat']。
    """
    out: dict[str, set[str]] = {}
    for d in DISCIPLINES.values():
        primary = d.get("cat")
        if not primary:
            continue
        match_set = {primary, *d.get("cats", [])}
        for c in match_set:
            out.setdefault(c, set()).add(primary)
    return out


_OAI_CAT_TO_PRIMARY = _build_oai_cat_map()


def _build_primary_to_disciplines() -> dict[str, list[str]]:
    """primary_cat → 以該 cat 為主領域的 discipline id 清單(SSE 推播用反查表)。"""
    out: dict[str, list[str]] = {}
    for did, d in DISCIPLINES.items():
        primary = d.get("cat")
        if primary:
            out.setdefault(primary, []).append(did)
    return out


_PRIMARY_TO_DISCIPLINES = _build_primary_to_disciplines()

# #15 即時推播:有新論文落地時透過 SSE 通知開著的分頁。
_event_hub = EventHub()
_SSE_PING_S = 20  # 心跳間隔(秒);同時用來輪詢 client 斷線


async def _flush_task() -> None:
    while True:
        try:
            await asyncio.sleep(60)
            for s in (_s2_store, _pwc_store):
                await asyncio.to_thread(s.flush)
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

    async def _warm_subtopics(disc_id: str) -> None:
        """預熱 cluster:papers 已熱身完才有 embedding cache,所以這要在 _warm_one 之後跑。"""
        if not HF_TOKEN:
            return
        cache_key = f"{disc_id}|k=6"

        async def _build():
            try:
                papers = await _papers_for_discipline(disc_id)
            except Exception:
                return {"clusters": [], "discipline": disc_id, "reason": "pool_unavailable"}
            if not papers:
                return {"clusters": [], "discipline": disc_id, "reason": "empty_pool"}
            pool = papers[:200]
            try:
                clusters = await cluster_papers(_client(), pool, k=6, min_cluster=3)
            except Exception as e:
                logger.warning("warmup subtopics %s failed: %s", disc_id, e)
                return {"clusters": [], "discipline": disc_id, "reason": "cluster_failed"}
            return {"clusters": clusters, "discipline": disc_id, "pool_size": len(pool)}

        try:
            await _subtopics_cache.warm(cache_key, _build)
        except Exception as e:
            logger.warning("warmup subtopics %s outer failed: %s", disc_id, e)

    while True:
        try:
            await asyncio.gather(*[_warm_one(d) for d in _WARMUP_DISCIPLINES])
            try:
                await _trending_cache.warm("hf_daily:7", _trending_build_spec(7))
            except Exception as e:
                logger.warning("warmup trending failed: %s", e)
            # subtopics 預熱:序列跑,避免一次太多 HF 請求觸發限流
            for d in _WARMUP_DISCIPLINES:
                await _warm_subtopics(d)
            await asyncio.sleep(_WARMUP_INTERVAL)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # 任何漏網 exception 都不要讓整個 task 死掉,讓 SWR 繼續運作
            logger.warning("warmup loop error: %s", e)
            await asyncio.sleep(_WARMUP_INTERVAL)


async def _warmup_loop_tier2() -> None:
    """次層預熱:第二梯隊領域,間隔較長(15 分鐘)避免 arXiv 限流。

    Tier 2 命中時間敏感度低,但提高跨領域使用者首次體感。同樣有 Semaphore 保護。
    """
    await asyncio.sleep(60)  # 等 Tier 1 先完成一輪再啟動
    sem = asyncio.Semaphore(_WARMUP_CONCURRENCY)

    async def _warm_one(disc_id: str) -> None:
        async with sem:
            try:
                key, builder = _papers_build_spec(disc_id, _WARMUP_DAYS, _WARMUP_MAX)
                await _papers_cache.warm(key, builder)
            except Exception as e:
                logger.warning("warmup-t2 %s failed: %s", disc_id, e)

    while True:
        try:
            await asyncio.gather(*[_warm_one(d) for d in _WARMUP_DISCIPLINES_TIER2])
            await asyncio.sleep(_WARMUP_INTERVAL_TIER2)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("warmup-t2 loop error: %s", e)
            await asyncio.sleep(_WARMUP_INTERVAL_TIER2)


async def _stars_enrich_once() -> None:
    """對熱門領域近期論文解析 GitHub repo → 取 star → 寫回 snapshots。

    star 走背景補值而非請求路徑:GitHub API 慢且有限流,不能塞進 /api/papers 熱路徑。
    跨領域去重 slug 後一次抓取,再分領域以帶 published 的完整 payload 寫 snapshots
    (避免 published 空字串污染)。
    """
    by_cat: dict[str, list[dict]] = {}
    slug_to_url: dict[str, str] = {}
    for disc_id in _WARMUP_DISCIPLINES:
        cat = discipline(disc_id).get("cat") or ""
        if not cat or cat in by_cat:
            continue
        recent = await asyncio.to_thread(_paper_store.query, cat, _WARMUP_DAYS, _WARMUP_MAX)
        with_gh = [p for p in recent if p.get("github_url")]
        if not with_gh:
            continue
        by_cat[cat] = with_gh
        for p in with_gh:
            slug = github_repo_slug(p["github_url"])
            if slug:
                slug_to_url.setdefault(slug, p["github_url"])
    slugs = list(slug_to_url)[:_STARS_MAX_REPOS]
    if not slugs:
        return
    stars = await fetch_github_stars(_client(), slugs, token=_GITHUB_TOKEN)
    if not stars:
        return
    enriched_cats = 0
    for cat, papers in by_cat.items():
        rows = [
            {**p, "github_stars": stars[slug]}
            for p in papers
            if (slug := github_repo_slug(p.get("github_url") or "")) and slug in stars
        ]
        if rows:
            await asyncio.to_thread(_paper_store.record_snapshots, rows, cat)
            enriched_cats += 1
    logger.info("stars: enriched %d repos across %d cats", len(stars), enriched_cats)


async def _stars_loop() -> None:
    """背景 star 補值迴圈;等首輪 warm 把 papers 寫進 store 後啟動。"""
    await asyncio.sleep(90)
    while True:
        try:
            await _stars_enrich_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("stars loop error: %s", e)
        await asyncio.sleep(_STARS_INTERVAL)


def _oai_group_by_primary(papers: list[dict]) -> dict[str, list[dict]]:
    """把收割到的論文依其 categories 映射到各 discipline 的 primary_cat 桶。"""
    buckets: dict[str, list[dict]] = {}
    for p in papers:
        primaries: set[str] = set()
        for c in p.get("categories") or []:
            primaries |= _OAI_CAT_TO_PRIMARY.get(c, set())
        for primary in primaries:
            buckets.setdefault(primary, []).append(p)
    return buckets


async def _oai_harvest_once() -> None:
    """對每個 OAI set 收割自上次 datestamp 以來的新論文,分桶寫進 L2 store。

    state 推進到今天(datestamp 為日粒度,同日重跑為冪等 upsert)。set 之間留間隔
    避免對 arXiv OAI 連續施壓。
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cold_start = (datetime.now(timezone.utc) - timedelta(days=_OAI_COLD_START_DAYS)).strftime("%Y-%m-%d")
    affected_primaries: set[str] = set()
    for idx, oai_set in enumerate(_OAI_SETS):
        if idx > 0:
            await asyncio.sleep(5)
        from_date = await asyncio.to_thread(_paper_store.oai_get_state, oai_set) or cold_start
        try:
            papers = await harvest_arxiv_oai(
                _client(), oai_set, from_date=from_date,
                max_pages=_OAI_MAX_PAGES, max_records=_OAI_MAX_RECORDS,
            )
        except Exception as e:
            logger.warning("oai harvest %s failed: %s", oai_set, e)
            continue
        if not papers:
            await asyncio.to_thread(_paper_store.oai_set_state, oai_set, today)
            continue
        buckets = _oai_group_by_primary(papers)
        upserted = 0
        for primary, rows in buckets.items():
            n = await asyncio.to_thread(_paper_store.upsert_many, rows, primary)
            await asyncio.to_thread(_paper_store.record_snapshots, rows, primary)
            upserted += n
        affected_primaries |= buckets.keys()
        await asyncio.to_thread(_paper_store.oai_set_state, oai_set, today)
        logger.info(
            "oai harvest %s: %d papers → %d rows across %d cats (from %s)",
            oai_set, len(papers), upserted, len(buckets), from_date,
        )
    disc_ids = sorted({
        did for primary in affected_primaries
        for did in _PRIMARY_TO_DISCIPLINES.get(primary, [])
    })
    if disc_ids:
        _event_hub.publish({"type": "papers", "disciplines": disc_ids, "at": int(time.time())})


async def _oai_harvest_loop() -> None:
    """背景增量收割迴圈;等首輪 warmup 後啟動,每 _OAI_INTERVAL 跑一輪。"""
    await asyncio.sleep(120)
    while True:
        try:
            await _oai_harvest_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("oai harvest loop error: %s", e)
        await asyncio.sleep(_OAI_INTERVAL)


async def _reviews_aggregate() -> list[dict]:
    """聚合四大會議當年+前一年已評審的投稿,依 review_avg 排序。

    會議投稿審查期不掛 arXiv id,無法併進主 feed;此處獨立聚合給「評審熱度」視圖。
    各 venue-year 平行抓取,單一失敗 soft-fail。
    """
    year = time.gmtime().tm_year
    tasks = [
        fetch_openreview_listing(
            _client(), venue, year=yr,
            days=_REVIEWS_CYCLE_DAYS, max_results=_REVIEWS_PER_VENUE,
        )
        for venue in _REVIEWS_VENUES
        for yr in (year, year - 1)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    rated: list[dict] = []
    for res in results:
        if isinstance(res, Exception):
            continue
        rated.extend(p for p in res if p.get("review_avg"))
    rated.sort(key=lambda p: p.get("review_avg") or 0, reverse=True)
    return rated[:_REVIEWS_LIMIT]


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
    warm_t2 = asyncio.create_task(_warmup_loop_tier2())
    cleanup = asyncio.create_task(_paper_cleanup_task())
    stars = asyncio.create_task(_stars_loop())
    oai = asyncio.create_task(_oai_harvest_loop()) if _OAI_ENABLED and _OAI_SETS else None
    try:
        yield
    finally:
        flush.cancel()
        warm.cancel()
        warm_t2.cancel()
        cleanup.cancel()
        stars.cancel()
        if oai is not None:
            oai.cancel()
        for s in (_s2_store, _pwc_store):
            await asyncio.to_thread(s.flush)
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


# ── Static long-cache + security headers (pure ASGI: no body buffering) ──
class HeadersMiddleware:
    def __init__(self, app):
        self.app = app

    def _apply(self, headers: MutableHeaders, path: str) -> None:
        if path.startswith("/static/"):
            if path.endswith("/sw.js"):
                headers["Cache-Control"] = "no-cache"
            elif path.endswith((".woff2", ".woff", ".ttf", ".png", ".jpg", ".webp")):
                headers["Cache-Control"] = "public, max-age=2592000, immutable"
            elif path.endswith("/disciplines.js"):
                headers["Cache-Control"] = "public, max-age=300, must-revalidate"
            elif path.endswith((".css", ".js", ".svg")):
                headers["Cache-Control"] = "public, max-age=300, must-revalidate"
            else:
                headers["Cache-Control"] = "public, max-age=86400"
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        # HSTS: TLS terminates at the Fly edge; force https on the apex + subdomains.
        headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        # CSP: 唯一 inline script 是 index.html 的 JSON-LD,以 sha256 hash 放行;
        # style-src 保留 unsafe-inline (CSS-in-JS 與 :focus outline 樣式有 inline 需求)
        if not headers.get("Content-Security-Policy"):
            headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'sha256-rp6QQ0ouE7tj2BbEMIflchpTVG+LQoePo1NY8ph7K0w='; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "img-src 'self' data: https:; "
                "connect-src 'self'; "
                "frame-ancestors 'self'; "
                "font-src 'self' data: https://fonts.gstatic.com; "
                "object-src 'none'; "
                "base-uri 'self'; form-action 'self'"
            )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                self._apply(MutableHeaders(raw=message["headers"]), path)
            await send(message)

        await self.app(scope, receive, send_wrapper)


# ── 簡易 IP token bucket(免外部依賴,防濫用)── pure ASGI ─────────
class RateLimitMiddleware:
    """每 IP per-minute token bucket。寫入 user data 算高成本,GET 一律 cost=1。"""

    def __init__(self, app, burst: int = 600):
        self.app = app
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

    @staticmethod
    def _client_ip(scope) -> str:
        # Fly-Client-IP is set by the trusted Fly edge and cannot be spoofed by
        # the client, unlike X-Forwarded-For (kept only as a non-Fly fallback).
        fly = ""
        xff = ""
        for k, v in scope.get("headers", []):
            if k == b"fly-client-ip" and not fly:
                fly = v.decode("latin-1").strip()
            elif k == b"x-forwarded-for" and not xff:
                xff = v.decode("latin-1").split(",")[0].strip()
        if fly:
            return fly
        if xff:
            return xff
        client = scope.get("client")
        return client[0] if client else "unknown"

    @staticmethod
    async def _reject(send) -> None:
        body = _json.dumps({"detail": "rate limited"}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"retry-after", b"10"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api/") or path in ("/api/health", "/api/ready"):
            await self.app(scope, receive, send)
            return

        ip = self._client_ip(scope)
        now = time.time()
        self._sweep_idle(now)
        window = 60.0
        dq = self._buckets.setdefault(ip, deque())
        while dq and now - dq[0] > window:
            dq.popleft()

        if len(dq) >= self.burst:
            await self._reject(send)
            return

        # reserve the slot atomically (no await between the burst check and this append)
        # so concurrent in-flight requests for the same IP count against the budget
        dq.append(now)
        status = {"code": 200}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            status["code"] = 500
            raise
        finally:
            if status["code"] >= 500:  # refund failed requests so failures stay free
                try:
                    dq.remove(now)
                except ValueError:
                    pass


app.add_middleware(RateLimitMiddleware)
app.add_middleware(HeadersMiddleware)

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── routes ───────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"ok": True, "t": int(time.time())}


@app.get("/api/ready")
def ready():
    """Readiness:paper cache 暖了才算 ready。供監控/手動探測,不接 Fly health check
    (單機 + volume 不能 blue-green;若把這個接上 LB,arXiv 限流冷啟會誤判 unhealthy)。"""
    warm = _papers_cache.stats()["entries"] > 0
    if not warm:
        raise HTTPException(status_code=503, detail="cache cold")
    return {"ready": True, "entries": _papers_cache.stats()["entries"], "t": int(time.time())}


_SSR_PAPER_COUNT = 30
_SLIM_SUMMARY_MAX = 800   # 大部份摘要 < 600,800 留緩衝;省約 30% bytes
_SLIM_TITLE_MAX = 320
_SLIM_AUTHORS_MAX = 25


def _slim_paper(p: dict) -> dict:
    """壓掉 /api/papers payload:截斷長字串、丟掉前端不用的欄位。

    保留的欄位都直接被 buildCard()/applyFilter()/dedup 使用;丟掉的都不影響功能。
    可省 30-40% 傳輸,跨容器 SQLite L2 也跟著省。
    """
    title = (p.get("title") or "")[:_SLIM_TITLE_MAX]
    summary = (p.get("summary") or "")[:_SLIM_SUMMARY_MAX]
    authors = p.get("authors") or []
    if isinstance(authors, list) and len(authors) > _SLIM_AUTHORS_MAX:
        authors = authors[:_SLIM_AUTHORS_MAX]
    out: dict[str, Any] = {
        "title": title,
        "summary": summary,
        "url": p.get("url"),
        "published": p.get("published"),
        "authors": authors,
        "source": p.get("source"),
    }
    ext = p.get("external_ids")
    if ext:
        out["external_ids"] = ext
    # 跨來源佐證:同一篇被多個來源收錄 → 更值得關注(前端 hot-score / emerging 用)
    src = p.get("source")
    if isinstance(src, list) and len(src) > 1:
        out["source_count"] = len(src)
    if p.get("venue"):
        out["venue"] = p["venue"]
    if p.get("hf_upvotes"):
        out["hf_upvotes"] = p["hf_upvotes"]
    github_url = p.get("github_url") or extract_github_url(p.get("summary"))
    if github_url:
        out["github_url"] = github_url
    if p.get("github_stars"):
        out["github_stars"] = p["github_stars"]
    if p.get("citation_count"):
        out["citation_count"] = p["citation_count"]
    if p.get("or_rating"):
        out["or_rating"] = p["or_rating"]
    if p.get("review_avg"):
        out["review_avg"] = p["review_avg"]
    if p.get("review_count"):
        out["review_count"] = p["review_count"]
    return out


def _paper_source_names(p: dict[str, Any]) -> list[str]:
    raw = p.get("source")
    if isinstance(raw, str):
        candidates = [raw]
    elif isinstance(raw, (list, tuple, set)):
        candidates = [str(x) for x in raw]
    else:
        candidates = []
    seen: set[str] = set()
    out: list[str] = []
    for item in candidates:
        name = item.strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _source_counts(papers: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for paper in papers:
        for name in _paper_source_names(paper):
            counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _positive_number(value: Any) -> bool:
    try:
        return float(value or 0) > 0
    except (TypeError, ValueError):
        return False


def _papers_response_meta(
    papers: list[dict[str, Any]],
    attempted: list[str] | None = None,
    failures: list[str] | None = None,
) -> dict[str, Any]:
    source_counts = _source_counts(papers)
    signals = {
        "with_citations": sum(1 for p in papers if _positive_number(p.get("citation_count"))),
        "with_code": sum(1 for p in papers if p.get("github_url") or _positive_number(p.get("github_stars"))),
        "with_reviews": sum(1 for p in papers if p.get("review_avg") or p.get("or_rating")),
    }
    return {
        "count": len(papers),
        "source_counts": source_counts,
        "source_count": len(source_counts),
        "source_attempted": list(attempted or []),
        "source_failures": list(failures or []),
        "signals": signals,
    }


def _ssr_compact(p: dict, citation_count: int | None = None) -> dict:
    out = {
        "url": p.get("url"),
        "title": (p.get("title") or "")[:260],
        "summary": (p.get("summary") or "")[:280],
        "authors": p.get("authors") or [],
        "published": p.get("published"),
        "venue": p.get("venue"),
        "github_url": p.get("github_url"),
        "hf_upvotes": p.get("hf_upvotes") or 0,
        "external_ids": p.get("external_ids") or {},
    }
    if citation_count is not None and citation_count >= 0:
        out["citation_count"] = citation_count
    return out


_ARXIV_ID_RE_SSR = re.compile(r"(\d{4}\.\d{4,6})")


def _ssr_citations_for(papers: list[dict]) -> dict[str, int]:
    """從 _s2_store 快取批次撈引用數(用 arxiv_id 當 key);不發新請求,沒命中就略過。"""
    out: dict[str, int] = {}
    try:
        for p in papers:
            url = p.get("url") or ""
            if not url:
                continue
            ext = p.get("external_ids") or {}
            aid = ext.get("arxiv") if isinstance(ext, dict) else None
            if not aid:
                m = _ARXIV_ID_RE_SSR.search(url)
                if m:
                    aid = m.group(1)
            if not aid:
                continue
            try:
                entry = _s2_store.get(str(aid))
            except Exception:
                entry = None
            if entry and isinstance(entry, dict):
                cc = entry.get("citation_count")
                if isinstance(cc, int) and cc >= 0:
                    out[url] = cc
    except Exception:
        pass
    return out


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
            papers = (data.get("papers") or [])[:_SSR_PAPER_COUNT]
            if papers:
                cits = _ssr_citations_for(papers)
                compact = [_ssr_compact(p, cits.get(p.get("url"))) for p in papers]
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


def _canonical_max(max_results: int) -> int:
    """把任意 max_results 收斂到固定桶,讓 endpoint / 語意召回 / warmup 共用同一 cache key。"""
    for bucket in _CANONICAL_MAX_BUCKETS:
        if max_results <= bucket:
            return bucket
    return _CANONICAL_MAX_BUCKETS[-1]


# 伺服器端排序鍵:latest=最新日期;其餘為對應指標(缺值視為 0/空字串墊底)。
_PAPERS_SORT_KEYS: dict[str, Callable[[dict], Any]] = {
    "latest": lambda p: p.get("published") or "",
    "citations": lambda p: p.get("citation_count") or 0,
    "hf": lambda p: p.get("hf_upvotes") or 0,
    "stars": lambda p: p.get("github_stars") or 0,
    "reviews": lambda p: p.get("review_avg") or 0,
}


_TOPIC_MAXLEN = 64
_TOPIC_STRIP_RE = re.compile(r"[^\w\s\-]", re.UNICODE)


def _sanitize_topic(topic: str) -> str:
    """收窄用子主題清洗:去特殊字元、收斂空白、限長。空字串代表不收窄。"""
    if not topic:
        return ""
    t = _TOPIC_STRIP_RE.sub(" ", topic)
    t = " ".join(t.split())
    return t[:_TOPIC_MAXLEN].strip()


def _arxiv_terms_for_topic(topic: str) -> str:
    """把清洗後的子主題轉成 arXiv all-field 片語查詢(已去引號,安全內插)。"""
    return f'all:"{topic}"' if topic else ""


def _sort_papers(papers: list[dict], sort: str) -> list[dict]:
    """依指定指標降冪排序;未知 sort 原序返回。回傳新 list,不動原資料。"""
    key_fn = _PAPERS_SORT_KEYS.get(sort)
    if key_fn is None:
        return papers
    return sorted(papers, key=key_fn, reverse=True)


def _filter_papers_by_query(papers: list[dict], query: str) -> list[dict]:
    """標題/摘要/作者子字串過濾(case-insensitive)。"""
    q = query.lower()
    out: list[dict] = []
    for p in papers:
        hay = " ".join((
            p.get("title") or "",
            p.get("summary") or "",
            " ".join(p.get("authors") or ()),
        )).lower()
        if q in hay:
            out.append(p)
    return out


def _papers_build_spec(discipline_id: str, days: int, max_results: int, topic: str = ""):
    """回傳 (cache_key, builder coroutine factory) — 給 endpoint 與 warmup 共用。

    topic 非空時收窄各上游查詢(arXiv 全文片語 / S2·OpenAlex·Crossref search),
    並跳過 paper_store 寫入(避免收窄子集污染 emergence 基線)。
    """
    days = _bounded_int(days, default=7, min_value=1, max_value=_PAPERS_DAYS_MAX)
    max_results = _bounded_int(
        max_results,
        default=1000,
        min_value=1,
        max_value=_PAPERS_MAX_RESULTS,
    )
    if days >= 30 and max_results < 5000:
        max_results = 5000
    max_results = _canonical_max(max_results)
    topic = _sanitize_topic(topic)
    disc = discipline(discipline_id)
    arxiv_native = bool(disc.get("arxiv_native", True))
    openalex_concept = disc.get("openalex_concept")
    crossref_subject = disc.get("crossref_subject")
    pubmed_mesh = disc.get("pubmed_mesh")
    use_biorxiv = bool(disc.get("biorxiv"))
    use_medrxiv = bool(disc.get("medrxiv"))
    use_chemrxiv = bool(disc.get("chemrxiv"))
    disc_cats = [c for c in (disc.get("cats") or []) if c]
    cats_key = "+".join(disc_cats)
    cache_key = (
        f"{disc.get('cat','')}:{cats_key}:{openalex_concept or ''}:{crossref_subject or ''}:"
        f"{pubmed_mesh or ''}:{int(use_biorxiv)}:{int(use_medrxiv)}:{int(use_chemrxiv)}:"
        f"{int(arxiv_native)}:{days}:{max_results}:t={topic}"
    )

    arxiv_max = max_results if arxiv_native else min(max_results, 200)
    openalex_max = 0 if arxiv_native and not openalex_concept else min(max_results, 300)
    crossref_max = 0 if arxiv_native and not crossref_subject else min(max_results, 200)
    biorxiv_max = min(max_results, 150) if use_biorxiv else 0
    medrxiv_max = min(max_results, 150) if use_medrxiv else 0
    chemrxiv_max = min(max_results, 150) if use_chemrxiv else 0
    pubmed_max = min(max_results, 200) if pubmed_mesh else 0
    # S2 search 作為 arXiv 限流時的補強:只對 arxiv_native 領域開啟
    s2_max = min(max_results, 100) if arxiv_native else 0

    async def build():
        c = _client()
        failures: list[str] = []
        attempted: list[str] = []

        async def _safe(name: str, coro):
            try:
                return await coro
            except Exception as e:
                logger.warning("%s listing failed for %s: %s", name, discipline_id, e)
                failures.append(name)
                return []

        def _add_source(name: str, coro) -> None:
            attempted.append(name)
            tasks.append(_safe(name, coro))

        arxiv_terms = _arxiv_terms_for_topic(topic) or None
        tasks = []
        _add_source("arxiv", fetch_arxiv_listing(
            c, disc["cat"], days, arxiv_max, cats=disc_cats or None, terms=arxiv_terms,
        ))
        if s2_max > 0:
            s2_query = topic or disc.get("name") or disc.get("cat") or ""
            _add_source("s2", fetch_s2_search(
                c, query=s2_query, fos=s2_fos_for_cat(disc.get("cat", "")),
                days=days, max_results=s2_max,
            ))
        if openalex_max > 0:
            _add_source("openalex", fetch_openalex_listing(
                c, concept_id=openalex_concept, days=days, max_results=openalex_max,
                search_query=topic or (None if openalex_concept else disc.get("name")),
            ))
        if crossref_max > 0:
            _add_source("crossref", fetch_crossref_listing(
                c, subject=crossref_subject, days=days, max_results=crossref_max,
                search_query=topic or (None if crossref_subject else disc.get("name")),
            ))
        if biorxiv_max > 0:
            _add_source("biorxiv", fetch_biorxiv_listing(c, "biorxiv", days, biorxiv_max))
        if medrxiv_max > 0:
            _add_source("medrxiv", fetch_biorxiv_listing(c, "medrxiv", days, medrxiv_max))
        if chemrxiv_max > 0:
            _add_source("chemrxiv", fetch_chemrxiv_listing(c, days, chemrxiv_max))
        if pubmed_max > 0:
            _add_source("pubmed", fetch_pubmed_listing(c, pubmed_mesh, days, pubmed_max))

        sources = await asyncio.gather(*tasks)
        merged = merge_sources(*sources)
        merged = [_slim_paper(p) for p in merged]

        primary_cat = disc.get("cat") or ""
        # topic 收窄時不寫入 store:子集會扭曲 emergence 基線與廣域 L2 快照
        if merged and primary_cat and not topic:
            try:
                await asyncio.to_thread(_paper_store.upsert_many, merged, primary_cat)
                await asyncio.to_thread(_paper_store.record_snapshots, merged, primary_cat)
            except Exception as e:
                logger.warning("paper_store upsert failed for %s: %s", discipline_id, e)

        if not merged:
            # topic 收窄查無結果:若有上游失敗(如 arXiv 冷啟限流),拋錯不快取,
            # 讓下次請求重抓;若全部成功仍為空才視為「該子主題近期無新論文」,
            # 回空集(不走廣域 L2 fallback,否則回傳未收窄論文誤導使用者)。
            if topic:
                if failures:
                    raise RuntimeError(
                        f"topic feed sources failed for {discipline_id}/{topic}: {failures}"
                    )
                return {
                    "papers": [],
                    "arxiv_native": arxiv_native,
                    "topic": topic,
                    **_papers_response_meta([], attempted, failures),
                }
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
                    l2 = l2[:_PAPERS_RESPONSE_CAP]
                    return {
                        "papers": l2,
                        "arxiv_native": arxiv_native,
                        "from_l2": True,
                        "as_of": int(time.time()),
                        **_papers_response_meta(l2, attempted, failures),
                    }
            raise RuntimeError(f"all sources empty for {discipline_id}")
        # rank-before-truncate:跨來源以最新日期全域排序後才截斷,避免「先接進來的
        # 來源」吃光截斷額度、把較新但排在後面來源的論文丟掉(多來源領域尤其明顯)。
        merged = _sort_papers(merged, "latest")
        if len(merged) > _PAPERS_RESPONSE_CAP:
            merged = merged[:_PAPERS_RESPONSE_CAP]
        as_of = int(time.time())
        result = {
            "papers": merged,
            "arxiv_native": arxiv_native,
            "as_of": as_of,
            **_papers_response_meta(merged, attempted, failures),
        }
        if topic:
            result["topic"] = topic
        else:
            # 廣域快取(重)建成功 → 通知開著的分頁該領域有新資料
            _event_hub.publish(
                {"type": "papers", "disciplines": [discipline_id], "at": as_of}
            )
        return result

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
    sort: str = "latest",
    q: str = "",
    topic: str = "",
):
    days = _bounded_int(days, default=7, min_value=1, max_value=_PAPERS_DAYS_MAX)
    max_results = _bounded_int(
        max_results,
        default=1000,
        min_value=1,
        max_value=_PAPERS_MAX_RESULTS,
    )
    cache_key, builder = _papers_build_spec(discipline_id, days, max_results, topic=topic)
    body, etag = await _papers_cache.get_or_build(cache_key, builder)
    # 預設(latest + 無查詢)走快取直出;只有非預設排序或帶查詢時才反序列化轉換,
    # 讓前端常態請求零額外開銷(cache 存的是 bytes,canonical 已是 latest 序)。
    sort = (sort or "latest").lower()
    q = (q or "").strip()
    needs_transform = q or (sort in _PAPERS_SORT_KEYS and sort != "latest")
    if needs_transform:
        payload = _json.loads(body)
        papers = payload.get("papers", [])
        if q:
            papers = _filter_papers_by_query(papers, q)
        papers = _sort_papers(papers, sort if sort in _PAPERS_SORT_KEYS else "latest")
        payload = {
            **payload,
            "papers": papers,
            **_papers_response_meta(
                papers,
                payload.get("source_attempted") or [],
                payload.get("source_failures") or [],
            ),
        }
        body = _json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        etag = make_etag(body)
    return etag_response(request, body, etag)


_FEED_MAX_FIELDS = 8       # 合併 feed 一次最多併幾個領域
_FEED_PER_FIELD_MAX = 80   # 對齊 _canonical_max 桶 → days=7 時暖機領域零冷啟動


def _valid_field_ids(raw: str) -> list[str]:
    """逗號分隔 discipline id → 去重保序、濾掉未知 id、上限 _FEED_MAX_FIELDS。"""
    out: list[str] = []
    seen: set[str] = set()
    for tok in (raw or "").split(","):
        fid = tok.strip()
        if fid and fid in DISCIPLINES and fid not in seen:
            seen.add(fid)
            out.append(fid)
            if len(out) >= _FEED_MAX_FIELDS:
                break
    return out


@app.get("/api/feed")
async def get_combined_feed(
    request: Request,
    fields: str = "",
    days: int = 7,
    sort: str = "latest",
    q: str = "",
    max_results: int = 300,
):
    """合併「我的領域」feed(#14):多個 discipline 併成單一去重、排序的串流。

    各領域以與 /api/papers 相同的 cache 規格建構(預設 days=7、per-field 80 →
    對齊暖機桶,熱門領域零冷啟動);跨領域去重後保留每篇命中的領域標籤,
    讓前端標示來源並沿用單領域 feed 的排序/搜尋/卡片渲染。
    """
    field_ids = _valid_field_ids(fields)
    if not field_ids:
        raise HTTPException(status_code=400, detail="empty or unknown fields")
    days = _bounded_int(days, default=7, min_value=1, max_value=_PAPERS_DAYS_MAX)
    max_results = _bounded_int(
        max_results, default=300, min_value=1, max_value=_PAPERS_RESPONSE_CAP
    )

    async def _pool(fid: str) -> list[dict]:
        key, builder = _papers_build_spec(fid, days, _FEED_PER_FIELD_MAX)
        body, _etag = await _papers_cache.get_or_build(key, builder)
        return (_json.loads(body) or {}).get("papers") or []

    pools = await asyncio.gather(
        *[_pool(f) for f in field_ids], return_exceptions=True
    )

    merged: list[dict] = []
    index: dict[str, int] = {}
    for fid, pool in zip(field_ids, pools, strict=False):
        if isinstance(pool, Exception):
            logger.warning("feed: pool unavailable for %s: %s", fid, pool)
            continue
        fname = discipline(fid).get("name") or fid
        for p in pool:
            ext = p.get("external_ids") or {}
            k = (ext.get("arxiv") if isinstance(ext, dict) else "") or p.get("url") or p.get("title") or ""
            if not k:
                continue
            pos = index.get(k)
            if pos is not None:
                tags = merged[pos].setdefault("fields", [])
                if fid not in tags:
                    tags.append(fid)
                continue
            entry = dict(p)
            entry["fields"] = [fid]
            entry["field_name"] = fname
            index[k] = len(merged)
            merged.append(entry)

    q = (q or "").strip()
    if q:
        merged = _filter_papers_by_query(merged, q)
    sort = (sort or "latest").lower()
    merged = _sort_papers(merged, sort if sort in _PAPERS_SORT_KEYS else "latest")
    if len(merged) > max_results:
        merged = merged[:max_results]

    body = _json.dumps(
        {
            "papers": merged,
            "count": len(merged),
            "fields": field_ids,
            "as_of": int(time.time()),
            "combined": True,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return etag_response(request, body, make_etag(body))


@app.get("/api/stream")
async def stream(request: Request) -> StreamingResponse:
    """SSE 即時推播:有新論文落地時通知開著的分頁(#15)。

    單 worker 內以 EventHub 廣播;每 _SSE_PING_S 秒送一次心跳兼偵測斷線。
    事件格式 {"type":"papers","disciplines":[...],"at":epoch},client 自行判斷
    是否與當前領域相關。容量滿時回 503,client 端會自動重連。
    """
    queue = _event_hub.subscribe()
    if queue is None:
        raise HTTPException(status_code=503, detail="stream capacity reached")

    async def gen():
        try:
            yield b": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_SSE_PING_S)
                except asyncio.TimeoutError:
                    yield b": ping\n\n"
                    continue
                data = _json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                yield f"data: {data}\n\n".encode()
        finally:
            _event_hub.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/trending")
async def get_trending(request: Request, source: str = "hf_daily", days: int = 7):
    if source != "hf_daily":
        raise HTTPException(status_code=400, detail=f"unknown source: {source}")
    days = _bounded_int(days, default=7, min_value=1, max_value=_TRENDING_DAYS_MAX)
    cache_key = f"{source}:{days}"
    body, etag = await _trending_cache.get_or_build(cache_key, _trending_build_spec(days))
    return etag_response(request, body, etag)


def _emergence_score(d: dict) -> dict:
    """Poisson-normalized burst score for one snapshot delta row.

    delta / sqrt(baseline + prior) ≈ a z-score under a Poisson null (variance≈mean),
    so a small fast-growing paper beats a large slow-growing one.
    """
    cit_delta = max(0, int(d["cit_new"]) - int(d["cit_old"]))
    hf_delta = max(0, int(d["hf_new"]) - int(d["hf_old"]))
    star_delta = max(0, int(d.get("star_new", 0)) - int(d.get("star_old", 0)))
    cit_z = cit_delta / ((int(d["cit_old"]) + _EMERGE_CIT_PRIOR) ** 0.5)
    hf_z = hf_delta / ((int(d["hf_old"]) + _EMERGE_HF_PRIOR) ** 0.5)
    star_z = star_delta / ((int(d.get("star_old", 0)) + _EMERGE_STAR_PRIOR) ** 0.5)
    return {
        "cit_delta": cit_delta,
        "hf_delta": hf_delta,
        "star_delta": star_delta,
        "cit_z": round(cit_z, 3),
        "hf_z": round(hf_z, 3),
        "star_z": round(star_z, 3),
        "emergence": round(
            cit_z + _EMERGE_HF_WEIGHT * hf_z + _EMERGE_STAR_WEIGHT * star_z, 3
        ),
    }


@app.get("/api/emerging")
async def get_emerging(
    request: Request,
    discipline_id: str = Query(DEFAULT_DISCIPLINE, alias="discipline"),
    window: int = 7,
    limit: int = _EMERGING_LIMIT,
):
    """突發偵測:窗內引用/HF 投票成長最快的論文(大家正在關注什麼)。

    Poisson 正規化讓 0→5 的新秀勝過 100→105 的老牌。snapshot 表需 ≥2 個不同
    日期才有 delta,首次部署 1-2 天內回 warming_up=true 的空清單。
    """
    window = _bounded_int(window, default=7, min_value=2, max_value=_EMERGING_WINDOW_MAX)
    limit = _bounded_int(limit, default=_EMERGING_LIMIT, min_value=1, max_value=100)
    disc = discipline(discipline_id)
    primary_cat = disc.get("cat") or ""
    cache_key = f"{primary_cat}:{window}:{limit}"

    async def _build():
        if not primary_cat:
            return {"papers": [], "discipline": discipline_id, "warming_up": False}
        deltas = await asyncio.to_thread(
            _paper_store.metric_deltas, primary_cat, window, 300
        )
        scored: list[tuple[str, dict, dict]] = []
        for d in deltas:
            s = _emergence_score(d)
            if (s["cit_delta"] or s["hf_delta"] or s["star_delta"]) and s["emergence"] >= _EMERGE_MIN:
                scored.append((d["paper_id"], s, d))
        if not scored:
            return {
                "papers": [],
                "discipline": discipline_id,
                "warming_up": not deltas,
                "window": window,
            }
        scored.sort(key=lambda t: t[1]["emergence"], reverse=True)
        scored = scored[:limit]
        payloads = await asyncio.to_thread(
            _paper_store.payloads_by_ids, [pid for pid, _, _ in scored], primary_cat
        )
        papers: list[dict] = []
        for pid, s, d in scored:
            p = payloads.get(pid)
            if not p:
                continue
            item = _slim_paper(p)
            item["emergence"] = s
            item["cit_new"] = d["cit_new"]
            item["hf_now"] = d["hf_new"]
            item["star_now"] = d.get("star_new", 0)
            papers.append(item)
        return {
            "papers": papers,
            "discipline": discipline_id,
            "warming_up": False,
            "window": window,
            "pool": len(deltas),
        }

    body, etag = await _emerging_cache.get_or_build(cache_key, _build)
    return etag_response(request, body, etag)


async def _hot_build(window: int, limit: int) -> dict:
    """跨領域 emergence 聚合(/api/hot 的核心)。RSS view=hot 也共用此快取。"""
    specs: list[tuple[str, str, str]] = []
    for did in _HOT_DISCIPLINES:
        d = discipline(did)
        cat = d.get("cat") or ""
        if cat:
            specs.append((did, cat, d.get("name") or did))
    deltas_lists = await asyncio.gather(
        *[asyncio.to_thread(_paper_store.metric_deltas, cat, window, 300) for _, cat, _ in specs]
    )
    agg: dict[str, dict] = {}
    any_delta = False
    for (did, cat, name), deltas in zip(specs, deltas_lists, strict=False):
        if deltas:
            any_delta = True
        for d in deltas:
            s = _emergence_score(d)
            if not (s["cit_delta"] or s["hf_delta"] or s["star_delta"]):
                continue
            if s["emergence"] < _EMERGE_MIN:
                continue
            pid = d["paper_id"]
            cur = agg.get(pid)
            if cur is None:
                cur = {"score": s, "delta": d, "cat": cat, "fields": [], "field_names": []}
                agg[pid] = cur
            elif s["emergence"] > cur["score"]["emergence"]:
                cur["score"] = s
                cur["delta"] = d
                cur["cat"] = cat
            if did not in cur["fields"]:
                cur["fields"].append(did)
                cur["field_names"].append(name)
    if not agg:
        return {"papers": [], "count": 0, "warming_up": not any_delta, "window": window}
    ranked = sorted(
        agg.items(), key=lambda kv: kv[1]["score"]["emergence"], reverse=True
    )[:limit]
    by_cat: dict[str, list[str]] = {}
    for pid, info in ranked:
        by_cat.setdefault(info["cat"], []).append(pid)
    payloads: dict[str, dict] = {}
    fetched = await asyncio.gather(
        *[asyncio.to_thread(_paper_store.payloads_by_ids, pids, cat) for cat, pids in by_cat.items()]
    )
    for got in fetched:
        payloads.update(got)
    papers: list[dict] = []
    for pid, info in ranked:
        p = payloads.get(pid)
        if not p:
            continue
        item = _slim_paper(p)
        item["emergence"] = info["score"]
        item["cit_new"] = info["delta"]["cit_new"]
        item["hf_now"] = info["delta"]["hf_new"]
        item["star_now"] = info["delta"].get("star_new", 0)
        item["fields"] = info["fields"]
        item["field_name"] = info["field_names"][0] if info["field_names"] else None
        papers.append(item)
    return {
        "papers": papers,
        "count": len(papers),
        "warming_up": False,
        "window": window,
        "cross_discipline": True,
    }


@app.get("/api/hot")
async def get_hot(request: Request, window: int = 7, limit: int = _HOT_DEFAULT_LIMIT):
    """全領域熱榜(#20):跨所有追蹤領域聚合 emergence burst → 大家正在關注什麼。

    對每個 snapshot 追蹤的領域算 metric_deltas + emergence z-score,跨領域去重
    (同一篇橫跨多領域取最高分並累積領域標籤),依 emergence 排序回傳。需 snapshot
    表 ≥2 個日期才有 delta,冷啟期回 warming_up=true 空清單。
    """
    window = _bounded_int(window, default=7, min_value=2, max_value=_HOT_WINDOW_MAX)
    limit = _bounded_int(limit, default=_HOT_DEFAULT_LIMIT, min_value=1, max_value=_HOT_LIMIT_MAX)
    cache_key = f"{window}:{limit}"
    body, etag = await _hot_cache.get_or_build(
        cache_key, lambda: _hot_build(window, limit)
    )
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

    if len(papers) > _SEMANTIC_POOL_MAX:
        papers = papers[:_SEMANTIC_POOL_MAX]

    # Hybrid BM25 ⊕ dense via RRF. embedding 服務掛掉時自動退化成 BM25-only,
    # 召回端永不 502;只有 BM25 與 dense 同時無結果才算空。
    try:
        result = await hybrid_rank(_client(), query, papers, top_k=top_k)
    except Exception as e:
        logger.warning("hybrid_rank failed: %s", e)
        raise HTTPException(status_code=502, detail=f"ranking failure: {e}") from e

    return {
        "papers": result["papers"],
        "query": query,
        "discipline": used_disc,
        "model": HF_EMBED_MODEL,
        "pool_size": len(papers),
        "dense": result["dense"],
        "lexical": result["lexical"],
    }


@app.get("/api/disciplines")
def list_disciplines():
    return {
        "disciplines": [{"id": k, **v} for k, v in DISCIPLINES.items()],
        "default": DEFAULT_DISCIPLINE,
    }


# ── 動態子題:k-means on cached embeddings ───────────────────────
@app.get("/api/subtopics")
async def list_subtopics(
    discipline_id: str = Query(DEFAULT_DISCIPLINE, alias="discipline"),
    k: int = 6,
):
    """回傳 [{label, count, sample_titles}],只用既存 embedding cache,不打 HF。

    沒 HF_TOKEN 或 cache 空時回空清單(前端會略過動態 group)。
    """
    if not HF_TOKEN:
        return {"clusters": [], "discipline": discipline_id, "reason": "no_hf_token"}

    k = _bounded_int(k, default=6, min_value=2, max_value=10)
    cache_key = f"{discipline_id}|k={k}"

    async def _build():
        try:
            papers = await _papers_for_discipline(discipline_id)
        except Exception as e:
            logger.warning("subtopics: paper pool unavailable for %s: %s", discipline_id, e)
            return {"clusters": [], "discipline": discipline_id, "reason": "pool_unavailable"}
        if not papers:
            return {"clusters": [], "discipline": discipline_id, "reason": "empty_pool"}
        # 只取前 200 篇,降低聚類成本(k-means 是 O(n*k*iter))
        pool = papers[:200]
        try:
            clusters = await cluster_papers(_client(), pool, k=k, min_cluster=3)
        except Exception as e:
            logger.warning("subtopics: cluster failed for %s: %s", discipline_id, e)
            return {"clusters": [], "discipline": discipline_id, "reason": "cluster_failed"}
        return {"clusters": clusters, "discipline": discipline_id, "pool_size": len(pool)}

    body, _etag = await _subtopics_cache.get_or_build(cache_key, _build)
    return _json.loads(body)


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


# ── GitHub repo/star resolver (PwC successor) ────────────────────
# PwC 已於 2025-07 關站,改直接以 arXiv abstract 內的 github 連結 +
# GitHub API 取 star 數。回傳形狀維持 {arxiv_id: {github_url, stars}} 不變。
@app.get("/api/pwc")
async def get_pwc(request: Request, arxiv_ids: str):
    ids = _unique_csv(arxiv_ids, max_items=_PWC_IDS_MAX, field_name="ids")
    missing = [a for a in ids if _pwc_store.get(a) is None]
    if missing:
        gh_map = await asyncio.to_thread(_paper_store.github_urls_for_arxiv, missing)
        slug_by_id = {a: github_repo_slug(u) for a, u in gh_map.items() if u}
        slugs = sorted({s for s in slug_by_id.values() if s})
        stars_by_slug: dict[str, int] = {}
        if slugs:
            try:
                stars_by_slug = await fetch_github_stars(_client(), slugs, token=_GITHUB_TOKEN)
            except Exception as e:
                logger.warning("github star fetch failed: %s", e)
        for a in missing:
            slug = slug_by_id.get(a)
            _pwc_store.set(a, {
                "github_url": gh_map.get(a),
                "stars": stars_by_slug.get(slug, 0) if slug else 0,
            })

    out: dict[str, dict] = {}
    for a in ids:
        v = _pwc_store.get(a)
        if v and v.get("github_url"):
            out[a] = {"github_url": v.get("github_url"), "stars": v.get("stars", 0)}

    body = _json.dumps({"results": out}, ensure_ascii=False).encode("utf-8")
    etag = make_etag(body)
    return etag_response(request, body, etag)


# ── Cache + RL observability ─────────────────────────────────────
_METRICS_KEY = os.environ.get("METRICS_KEY", "")
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _metrics_guard(request: Request, key: str) -> None:
    """Fail-closed metrics auth.

    With METRICS_KEY set → require an exact (constant-time) match.
    Without a key configured → allow loopback only, so a misconfigured prod
    deploy never exposes internals to the public edge.
    """
    if _METRICS_KEY:
        if not secrets.compare_digest(key, _METRICS_KEY):
            raise HTTPException(status_code=403, detail="forbidden")
        return
    client = request.client
    host = client.host if client else ""
    if host not in _LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail="metrics key not configured")


def _process_rss_bytes() -> int:
    """Resident set size in bytes; 0 when unavailable (e.g. Windows dev)."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    try:
        import resource
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    except Exception:
        return 0


@app.get("/api/metrics")
def get_metrics(request: Request, key: str = ""):
    """供 dashboard / 自我觀測用。設定 METRICS_KEY 環境變數後需帶 ?key=..."""
    _metrics_guard(request, key)
    return {
        "process_rss_bytes": _process_rss_bytes(),
        "papers_cache": _papers_cache.stats(),
        "trending_cache": _trending_cache.stats(),
        "s2_store": {"entries": len(_s2_store._data)},
        "pwc_store": {"entries": len(_pwc_store._data)},
        "semantic_cache": semantic_cache_stats(),
        "paper_store": _paper_store.stats(),
    }


def _prom_format(metric: str, value: float, labels: dict[str, str] | None = None, mtype: str = "gauge", help_text: str = "") -> str:
    """渲染單一 Prometheus exposition line(含 HELP/TYPE 標頭)。"""
    label_str = ""
    if labels:
        parts = [f'{k}="{str(v).replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))}"' for k, v in labels.items()]
        label_str = "{" + ",".join(parts) + "}"
    return f"# HELP {metric} {help_text}\n# TYPE {metric} {mtype}\n{metric}{label_str} {value}\n"


@app.get("/metrics")
def prometheus_metrics(request: Request, key: str = ""):
    """Prometheus exposition format。受 METRICS_KEY 保護。

    暴露 cache hit/miss、store 大小、warmup 結果、build error 計數、RSS。
    用法:scrape /metrics?key=$METRICS_KEY 進 Grafana / Prometheus。
    """
    _metrics_guard(request, key)

    lines: list[str] = []
    # process memory (key signal on the 512MB machine)
    rss = _process_rss_bytes()
    if rss > 0:
        lines.append(_prom_format(
            "cv_process_rss_bytes", rss,
            help_text="Resident set size in bytes",
        ))
    # cache hit/miss counters
    for cname, cobj in (
        ("papers", _papers_cache),
        ("trending", _trending_cache),
        ("subtopics", _subtopics_cache),
    ):
        s = cobj.stats()
        for field in ("hit_fresh", "hit_stale", "miss", "build_err", "warm_ok", "warm_skip"):
            v = int(s.get(field, 0))
            lines.append(_prom_format(
                f"cv_cache_{field}_total", v,
                labels={"cache": cname},
                mtype="counter",
                help_text=f"CachedJSON {field} count",
            ))
        lines.append(_prom_format(
            "cv_cache_entries", int(s.get("entries", 0)),
            labels={"cache": cname},
            help_text="CachedJSON in-memory entry count",
        ))
        lines.append(_prom_format(
            "cv_cache_hit_rate", float(s.get("hit_rate", 0.0)),
            labels={"cache": cname},
            help_text="CachedJSON cumulative hit rate",
        ))
        lines.append(_prom_format(
            "cv_cache_inflight", int(s.get("inflight", 0)),
            labels={"cache": cname},
            help_text="CachedJSON concurrent builders inflight",
        ))

    # KV stores
    lines.append(_prom_format("cv_kv_entries", len(_s2_store._data), labels={"store": "s2"}, help_text="LRUStore entry count"))
    lines.append(_prom_format("cv_kv_entries", len(_pwc_store._data), labels={"store": "pwc"}, help_text="LRUStore entry count"))

    # paper_store (L2 SQLite)
    try:
        ps = _paper_store.stats()
        for k, v in ps.items():
            if isinstance(v, (int, float)):
                lines.append(_prom_format(f"cv_paper_store_{k}", v, help_text=f"PaperStore {k}"))
    except Exception:
        pass

    # semantic embed cache
    try:
        ss = semantic_cache_stats()
        for k, v in ss.items():
            if isinstance(v, (int, float)):
                lines.append(_prom_format(f"cv_semantic_cache_{k}", v, help_text=f"Embed cache {k}"))
    except Exception:
        pass

    body = "".join(lines)
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")


# ── OpenReview (ICLR / NeurIPS / ICML 投稿 + 評審) ────────────────
_OPENREVIEW_VENUES = {"iclr", "neurips", "icml", "colm"}
_openreview_cache = CachedJSON(ttl=30 * 60, stale_ttl=24 * 3600, max_keys=32)


@app.get("/api/openreview")
async def get_openreview(
    request: Request,
    venue: str = Query("iclr"),
    year: int | None = None,
    days: int = _OPENREVIEW_DAYS_MAX,
    max_results: int = 200,
):
    venue = venue.lower()
    if venue not in _OPENREVIEW_VENUES:
        raise HTTPException(
            status_code=400, detail=f"unknown venue: {venue}; expected one of {_OPENREVIEW_VENUES}"
        )
    days = _bounded_int(days, default=_OPENREVIEW_DAYS_MAX, min_value=1, max_value=_OPENREVIEW_DAYS_MAX)
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


_reviews_cache = CachedJSON(ttl=6 * 3600, stale_ttl=24 * 3600, max_keys=2)


@app.get("/api/reviews")
async def get_reviews(request: Request):
    """評審熱度:四大會議當前審查週期評分最高的投稿(跨 venue 聚合、依 review_avg 排序)。"""
    async def build():
        papers = await _reviews_aggregate()
        return {"papers": papers, "count": len(papers)}

    body, etag = await _reviews_cache.get_or_build("reviews", build)
    return etag_response(request, body, etag)


# ── 熱門度:匿名開啟次數遙測 ────────────────────────────────────
_popular_cache = CachedJSON(ttl=120, stale_ttl=600, max_keys=8)


def _beacon_paper_id(arxiv_id: str, url: str, title: str) -> str:
    """Derive the same stable paper_id the store uses, from beacon fields."""
    stub: dict[str, Any] = {}
    if arxiv_id:
        stub["external_ids"] = {"arxiv": arxiv_id}
    if url:
        stub["url"] = url
    if title:
        stub["title"] = title
    return _derive_paper_id(stub)


@app.post("/api/view")
async def record_view(request: Request):
    """Anonymous open-count beacon. Body: {url?, arxiv_id?, title?}. Returns 204."""
    try:
        raw = await request.body()
        data = _json.loads(raw) if raw else {}
    except (ValueError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail="invalid body") from e
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="invalid body")
    arxiv_id = str(data.get("arxiv_id") or "").strip()[:40]
    url = str(data.get("url") or "").strip()[:_VIEW_URL_MAX]
    title = str(data.get("title") or "").strip()[:_VIEW_TITLE_MAX]
    if url and not url.startswith(("http://", "https://")):
        url = ""
    if not (arxiv_id or url or title):
        raise HTTPException(status_code=400, detail="empty beacon")
    pid = _beacon_paper_id(arxiv_id, url, title)
    await asyncio.to_thread(_paper_store.record_view, pid, url, title)
    return Response(status_code=204)


@app.get("/api/popular")
async def get_popular(request: Request, days: int = 7, limit: int = 40):
    """Most-opened papers in the trailing window (anonymous view counts)."""
    days = _bounded_int(days, default=7, min_value=1, max_value=_POPULAR_DAYS_MAX)
    limit = _bounded_int(limit, default=40, min_value=1, max_value=_POPULAR_LIMIT_MAX)
    cache_key = f"{days}:{limit}"

    async def build():
        papers = await asyncio.to_thread(_paper_store.top_viewed, days, limit)
        return {"papers": papers, "count": len(papers), "days": days}

    body, etag = await _popular_cache.get_or_build(cache_key, build)
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
