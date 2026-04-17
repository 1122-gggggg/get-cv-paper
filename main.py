import asyncio
import hashlib
import json as _json
import logging
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from huggingface_hub import InferenceClient
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ARXIV_BASE = "http://export.arxiv.org/api/query"
ARXIV_UA = "Mozilla/5.0 DesktopDashboard/1.0"
CACHE_DIR = Path(os.environ.get("CACHE_DIR", ".cache"))
CACHE_DIR.mkdir(exist_ok=True)


# ── Bounded LRU cache helper（支援 JSON 落地） ────────────────────
class LRUStore:
    def __init__(self, name: str, maxsize: int, ttl: float, persist: bool = True):
        self.name = name
        self.maxsize = maxsize
        self.ttl = ttl
        self.persist = persist
        self.path = CACHE_DIR / f"{name}.json"
        self._data: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self.persist or not self.path.exists():
            return
        try:
            raw = _json.loads(self.path.read_text("utf-8"))
            if isinstance(raw, dict):
                self._data = OrderedDict(raw)
        except Exception as e:
            logger.warning("cache %s load failed: %s", self.name, e)

    def flush(self) -> None:
        if not self.persist or not self._dirty:
            return
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(_json.dumps(self._data), encoding="utf-8")
            tmp.replace(self.path)
            self._dirty = False
        except Exception as e:
            logger.warning("cache %s flush failed: %s", self.name, e)

    def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if not entry:
            return None
        if self.ttl and time.time() - entry.get("at", 0) > self.ttl:
            self._data.pop(key, None)
            self._dirty = True
            return None
        self._data.move_to_end(key)
        return entry.get("v")

    def set(self, key: str, value: Any) -> None:
        self._data[key] = {"at": time.time(), "v": value}
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)
        self._dirty = True


_paper_store = LRUStore("papers", maxsize=16, ttl=3600, persist=False)
_s2_store = LRUStore("s2", maxsize=20000, ttl=6 * 3600)
_pwc_store = LRUStore("pwc", maxsize=20000, ttl=24 * 3600)
_summary_store = LRUStore("summary", maxsize=5000, ttl=0)


# ── HTTP client 單例 ─────────────────────────────────────────────
_http_client: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": ARXIV_UA},
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            http2=False,
            follow_redirects=True,
        )
    return _http_client


async def _flush_task():
    while True:
        await asyncio.sleep(60)
        for s in (_s2_store, _pwc_store, _summary_store):
            s.flush()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_flush_task())
    try:
        yield
    finally:
        task.cancel()
        for s in (_s2_store, _pwc_store, _summary_store):
            s.flush()
        if _http_client is not None:
            await _http_client.aclose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ── Static long-cache + security headers ─────────────────────────
class HeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/"):
            # sw.js 不得長快取，否則新版 SW 卡住
            if path.endswith("/sw.js"):
                response.headers["Cache-Control"] = "no-cache"
            else:
                response.headers["Cache-Control"] = "public, max-age=86400"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        return response


# ── 簡易 IP token bucket（免外部依賴，防濫用）────────────────────
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rate: int = 60, burst: int = 120, cost_write: int = 5):
        super().__init__(app)
        self.rate = rate  # tokens per minute
        self.burst = burst
        self.cost_write = cost_write
        self._buckets: dict[str, deque] = {}

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
        window = 60.0
        dq = self._buckets.setdefault(ip, deque())
        while dq and now - dq[0] > window:
            dq.popleft()
        cost = self.cost_write if request.method in ("PUT", "POST", "DELETE") else 1
        if len(dq) + cost > self.burst:
            return Response(
                content=_json.dumps({"detail": "rate limited"}),
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "30"},
            )
        for _ in range(cost):
            dq.append(now)
        return await call_next(request)


app.add_middleware(RateLimitMiddleware)
app.add_middleware(HeadersMiddleware)


@app.get("/api/health")
def health():
    return {"ok": True, "t": int(time.time())}

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── arXiv 論文 ────────────────────────────────────────────────────
_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
_ARXIV_ID_RE = re.compile(r"\(arXiv:.*?\)")


async def _http_get_bytes(url: str, timeout: float = 30.0) -> bytes:
    r = await _client().get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def _parse_arxiv_entries(xml_data: bytes, cutoff: datetime | None) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_data)
    papers: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", _ARXIV_NS):
        title_el = entry.find("atom:title", _ARXIV_NS)
        id_el = entry.find("atom:id", _ARXIV_NS)
        if title_el is None or title_el.text is None or id_el is None:
            continue

        title = _ARXIV_ID_RE.sub("", title_el.text.strip().replace("\n", " ")).strip()

        summary_el = entry.find("atom:summary", _ARXIV_NS)
        summary = summary_el.text.strip().replace("\n", " ") if summary_el is not None and summary_el.text else ""

        pub_el = entry.find("atom:published", _ARXIV_NS)
        pub_raw = pub_el.text if pub_el is not None else ""
        try:
            pub_date = datetime.strptime(pub_raw, "%Y-%m-%dT%H:%M:%SZ")
            if cutoff is not None and pub_date < cutoff:
                continue
            published_str = pub_date.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            published_str = pub_raw

        authors = [
            a.find("atom:name", _ARXIV_NS).text
            for a in entry.findall("atom:author", _ARXIV_NS)
            if a.find("atom:name", _ARXIV_NS) is not None
        ]

        papers.append({
            "title": title,
            "summary": summary,
            "url": id_el.text,
            "published": published_str,
            "authors": authors,
        })
    return papers


_papers_etag: dict[str, str] = {}


def _make_etag(payload: bytes) -> str:
    return 'W/"' + hashlib.md5(payload).hexdigest()[:16] + '"'


@app.get("/api/papers")
async def get_papers(request: Request, max_results: int = 1000, days: int = 7):
    if days >= 30 and max_results < 5000:
        max_results = 5000

    cache_key = f"{days}:{max_results}"
    cached = _paper_store.get(cache_key)
    if cached is not None:
        etag = _papers_etag.get(cache_key)
        if etag and request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "public, max-age=300"})
        if etag:
            body = _json.dumps({"papers": cached}, ensure_ascii=False).encode("utf-8")
            return Response(content=body, media_type="application/json",
                            headers={"ETag": etag, "Cache-Control": "public, max-age=300"})
        return {"papers": cached}

    url = (
        f"{ARXIV_BASE}?search_query=cat:cs.CV"
        f"&sortBy=submittedDate&sortOrder=descending&max_results={max_results}"
    )
    try:
        xml_data = await _http_get_bytes(url, timeout=30.0)
    except Exception as e:
        logger.error("arXiv API failed: %s", e)
        raise HTTPException(status_code=502, detail="arXiv upstream unavailable")

    cutoff = datetime.now() - timedelta(days=days)
    papers = _parse_arxiv_entries(xml_data, cutoff)
    _paper_store.set(cache_key, papers)
    body = _json.dumps({"papers": papers}, ensure_ascii=False).encode("utf-8")
    etag = _make_etag(body)
    _papers_etag[cache_key] = etag
    return Response(content=body, media_type="application/json",
                    headers={"ETag": etag, "Cache-Control": "public, max-age=300"})


@app.get("/api/search")
async def search_papers(q: str, max_results: int = 50):
    if not q.strip():
        return {"papers": []}

    encoded_q = urllib.parse.quote(q.strip())
    url = (
        f"{ARXIV_BASE}?search_query=all:{encoded_q}"
        f"&sortBy=relevance&sortOrder=descending&max_results={max_results}"
    )
    try:
        xml_data = await _http_get_bytes(url, timeout=20.0)
    except Exception as e:
        logger.error("arXiv search failed: %s", e)
        raise HTTPException(status_code=502, detail="arXiv upstream unavailable")

    return {"papers": _parse_arxiv_entries(xml_data, cutoff=None)}


@app.get("/")
def read_root():
    return FileResponse("static/index.html")


@app.get("/sw.js")
def sw_root():
    # 讓 Service Worker 以根路徑作用域註冊
    return FileResponse("static/sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


# ── Semantic Scholar citation proxy ───────────────────────────────
_S2_URL = (
    "https://api.semanticscholar.org/graph/v1/paper/batch"
    "?fields=citationCount,influentialCitationCount,referenceCount,venue,publicationVenue"
)


class CitationsRequest(BaseModel):
    arxiv_ids: list[str]


@app.post("/api/citations")
async def get_citations(req: CitationsRequest):
    result: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for aid in req.arxiv_ids:
        cached = _s2_store.get(aid)
        if cached is not None:
            result[aid] = cached
        else:
            missing.append(aid)

    if missing:
        for i in range(0, len(missing), 500):
            chunk = missing[i:i + 500]
            try:
                r = await _client().post(
                    _S2_URL,
                    json={"ids": [f"ArXiv:{a}" for a in chunk]},
                    timeout=15.0,
                )
                data = r.json() if r.status_code == 200 else []
            except Exception as e:
                logger.warning("S2 batch failed: %s", e)
                break
            for aid, item in zip(chunk, data):
                if not isinstance(item, dict):
                    continue
                entry = {
                    "count": item.get("citationCount") or 0,
                    "influential": item.get("influentialCitationCount") or 0,
                    "refs": item.get("referenceCount") or 0,
                    "venue": (item.get("publicationVenue") or {}).get("name") or item.get("venue") or "",
                }
                _s2_store.set(aid, entry)
                result[aid] = entry

    return {"results": result}


# ── Papers with Code proxy ────────────────────────────────────────
async def _fetch_pwc_one(arxiv_id: str) -> dict[str, Any]:
    entry: dict[str, Any] = {"github_url": None, "stars": 0}
    try:
        r = await _client().get(
            f"https://paperswithcode.com/api/v1/papers/?arxiv_id={arxiv_id}",
            timeout=10.0,
        )
        if r.status_code != 200:
            return entry
        data = r.json()
    except Exception:
        return entry

    result = (data.get("results") or [None])[0]
    if not result:
        return entry
    entry["github_url"] = result.get("github_url")
    rid = result.get("id")
    if rid:
        try:
            r2 = await _client().get(
                f"https://paperswithcode.com/api/v1/paper/{rid}/repositories/",
                timeout=10.0,
            )
            repo_data = r2.json() if r2.status_code == 200 else {}
        except Exception:
            repo_data = {}
        results = (repo_data or {}).get("results") or []
        top = next((r for r in results if r.get("is_official")), results[0] if results else None)
        if top:
            entry["stars"] = top.get("stars") or 0
            entry["github_url"] = top.get("url") or entry["github_url"]
    return entry


@app.get("/api/pwc")
async def get_pwc(arxiv_ids: str):
    ids = [a.strip() for a in arxiv_ids.split(",") if a.strip()]

    missing = [a for a in ids if _pwc_store.get(a) is None]

    if missing:
        sem = asyncio.Semaphore(5)

        async def _bounded(aid: str):
            async with sem:
                _pwc_store.set(aid, await _fetch_pwc_one(aid))

        await asyncio.gather(*[_bounded(a) for a in missing])

    out = {}
    for a in ids:
        v = _pwc_store.get(a)
        if v:
            out[a] = {"github_url": v.get("github_url"), "stars": v.get("stars", 0)}
    return {"results": out}


# ── Google Translate proxy（避免前端直接呼叫外部）────────────────
class TranslateRequest(BaseModel):
    text: str
    target: str = "zh-TW"


@app.post("/api/translate")
async def translate(req: TranslateRequest):
    text = (req.text or "").strip()
    if not text:
        return {"translated": ""}
    short = text[:1000]
    url = (
        "https://translate.googleapis.com/translate_a/single?client=gtx"
        f"&sl=en&tl={urllib.parse.quote(req.target)}&dt=t&q={urllib.parse.quote(short)}"
    )
    try:
        r = await _client().get(url, timeout=10.0)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail="translate failed")
        data = r.json()
        translated = "".join(item[0] for item in (data[0] or []) if item and item[0])
        return {"translated": translated}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("translate proxy failed: %s", e)
        raise HTTPException(status_code=502, detail="translate upstream failed")


# ── HuggingFace Gemma 中文摘要 ────────────────────────────────────
_hf_client: InferenceClient | None = None
HF_TOKEN = os.environ.get("HF_TOKEN", "")
HF_MODEL = os.environ.get("HF_MODEL", "google/gemma-2-27b-it")
HF_PROVIDER = os.environ.get("HF_PROVIDER") or None


SUMMARIZE_PROMPT = (
    "你是一位電腦視覺研究助理。請根據以下論文摘要，用繁體中文輸出結構化重點分析。"
    "嚴格按照以下格式輸出，每個項目用一到兩句話，不要多餘說明：\n\n"
    "🔍 核心問題：\n"
    "⚙️ 提出方法：\n"
    "🏆 主要貢獻：\n"
    "📊 實驗結果：\n\n"
    "論文摘要：\n"
)


class SummarizeRequest(BaseModel):
    arxiv_id: str
    abstract: str


def _blocking_summarize(text: str) -> str:
    global _hf_client
    if _hf_client is None:
        _hf_client = InferenceClient(token=HF_TOKEN, provider=HF_PROVIDER)
    resp = _hf_client.chat.completions.create(
        model=HF_MODEL,
        messages=[{"role": "user", "content": SUMMARIZE_PROMPT + text}],
        max_tokens=300,
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


@app.post("/api/summarize")
async def summarize(req: SummarizeRequest):
    if not HF_TOKEN:
        raise HTTPException(status_code=503, detail="HF_TOKEN not set")

    cached = _summary_store.get(req.arxiv_id)
    if cached is not None:
        return {"summary": cached}

    text = req.abstract[:2000]
    try:
        summary = await asyncio.to_thread(_blocking_summarize, text)
    except Exception as e:
        logger.error("summarize failed: %s", e)
        raise HTTPException(status_code=502, detail="summarization upstream failed")

    _summary_store.set(req.arxiv_id, summary)
    return {"summary": summary}


# ── Google 登入 + 雲端同步 ──────────────────────────────────────
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
_db_pool = None


async def _get_pool():
    global _db_pool
    if _db_pool is None:
        if not DATABASE_URL:
            raise HTTPException(status_code=503, detail="DATABASE_URL not set")
        import asyncpg
        _db_pool = await asyncpg.create_pool(
            DATABASE_URL, min_size=1, max_size=5, ssl="require",
            statement_cache_size=0,
        )
        async with _db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_data (
                    google_sub TEXT PRIMARY KEY,
                    email TEXT,
                    name TEXT,
                    data JSONB NOT NULL DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
    return _db_pool


def _verify_id_token(token: str) -> dict:
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="GOOGLE_CLIENT_ID not set")
    try:
        from google.oauth2 import id_token as gid_token
        from google.auth.transport import requests as g_requests
        info = gid_token.verify_oauth2_token(token, g_requests.Request(), GOOGLE_CLIENT_ID)
        return info
    except Exception as e:
        logger.warning("ID token verify failed: %s", e)
        raise HTTPException(status_code=401, detail="invalid token")


async def _require_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return _verify_id_token(authorization.split(None, 1)[1].strip())


@app.get("/api/me/data")
async def get_my_data(user: dict = Depends(_require_user)):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT data FROM user_data WHERE google_sub = $1", user["sub"])
    return {
        "user": {
            "email": user.get("email"),
            "name": user.get("name"),
            "picture": user.get("picture"),
        },
        "data": (row["data"] if row else {}) or {},
    }


class UserDataPut(BaseModel):
    data: dict = Field(default_factory=dict)


MAX_USER_DATA_BYTES = 512 * 1024  # 512KB per user（Supabase 免費層足夠）


@app.put("/api/me/data")
async def put_my_data(body: UserDataPut, user: dict = Depends(_require_user)):
    payload = _json.dumps(body.data)
    if len(payload.encode("utf-8")) > MAX_USER_DATA_BYTES:
        raise HTTPException(status_code=413, detail="user data too large")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_data (google_sub, email, name, data, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, now())
            ON CONFLICT (google_sub) DO UPDATE
              SET email = EXCLUDED.email,
                  name = EXCLUDED.name,
                  data = EXCLUDED.data,
                  updated_at = now()
            """,
            user["sub"], user.get("email"), user.get("name"), payload,
        )
    return {"ok": True}


@app.get("/api/me/config")
def get_auth_config():
    return {"google_client_id": GOOGLE_CLIENT_ID}
