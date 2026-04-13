import asyncio
import logging
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from huggingface_hub import InferenceClient
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ── Static long-cache headers ─────────────────────────────────────
class StaticCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response


app.add_middleware(StaticCacheMiddleware)

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── arXiv paper cache (keyed by days+max_results) ─────────────────
_paper_cache: dict[str, dict[str, Any]] = {}
CACHE_TTL = 3600  # 1 hour
ARXIV_BASE = "http://export.arxiv.org/api/query"
ARXIV_UA = "Mozilla/5.0 DesktopDashboard/1.0"

_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
_ARXIV_ID_RE = re.compile(r"\(arXiv:.*?\)")


def _blocking_get(url: str, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ARXIV_UA})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


async def _http_get(url: str, timeout: float = 30.0) -> bytes:
    return await asyncio.to_thread(_blocking_get, url, timeout)


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


@app.get("/api/papers")
async def get_papers(max_results: int = 1000, days: int = 7):
    if days >= 30 and max_results < 5000:
        max_results = 5000

    cache_key = f"{days}:{max_results}"
    cache = _paper_cache.get(cache_key)
    now = time.time()
    if cache and now - cache["timestamp"] < CACHE_TTL and cache["papers"]:
        return {"papers": cache["papers"]}

    url = (
        f"{ARXIV_BASE}?search_query=cat:cs.CV"
        f"&sortBy=submittedDate&sortOrder=descending&max_results={max_results}"
    )
    try:
        xml_data = await _http_get(url, timeout=30.0)
    except Exception as e:
        logger.error("arXiv API failed: %s", e)
        if cache and cache["papers"]:
            return {"papers": cache["papers"]}
        raise HTTPException(status_code=502, detail="arXiv upstream unavailable")

    cutoff = datetime.now() - timedelta(days=days)
    papers = _parse_arxiv_entries(xml_data, cutoff)

    _paper_cache[cache_key] = {"timestamp": now, "papers": papers}
    return {"papers": papers}


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
        xml_data = await _http_get(url, timeout=20.0)
    except Exception as e:
        logger.error("arXiv search failed: %s", e)
        raise HTTPException(status_code=502, detail="arXiv upstream unavailable")

    return {"papers": _parse_arxiv_entries(xml_data, cutoff=None)}


@app.get("/")
def read_root():
    return FileResponse("static/index.html")


# ── Semantic Scholar citation proxy (shared server cache) ─────────
_S2_TTL = 6 * 3600
_S2_URL = (
    "https://api.semanticscholar.org/graph/v1/paper/batch"
    "?fields=citationCount,influentialCitationCount,referenceCount,venue,publicationVenue"
)
_s2_cache: dict[str, dict[str, Any]] = {}


class CitationsRequest(BaseModel):
    arxiv_ids: list[str]


def _blocking_post_json(url: str, payload: bytes, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": ARXIV_UA},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


@app.post("/api/citations")
async def get_citations(req: CitationsRequest):
    import json as _json

    now = time.time()
    result: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for aid in req.arxiv_ids:
        cached = _s2_cache.get(aid)
        if cached and now - cached["at"] < _S2_TTL:
            result[aid] = cached
        else:
            missing.append(aid)

    if missing:
        # S2 batch accepts up to 500 ids per call
        for i in range(0, len(missing), 500):
            chunk = missing[i:i + 500]
            payload = _json.dumps({"ids": [f"ArXiv:{a}" for a in chunk]}).encode("utf-8")
            try:
                raw = await asyncio.to_thread(_blocking_post_json, _S2_URL, payload, 15.0)
                data = _json.loads(raw)
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
                    "at": now,
                }
                _s2_cache[aid] = entry
                result[aid] = entry

    return {"results": {k: {kk: vv for kk, vv in v.items() if kk != "at"} for k, v in result.items()}}


# ── Papers with Code proxy (shared server cache) ──────────────────
_PWC_TTL = 24 * 3600
_pwc_cache: dict[str, dict[str, Any]] = {}


def _blocking_get_json(url: str, timeout: float = 10.0) -> dict | None:
    import json as _json

    try:
        req = urllib.request.Request(url, headers={"User-Agent": ARXIV_UA})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return _json.loads(response.read())
    except Exception:
        return None


async def _fetch_pwc_one(arxiv_id: str) -> dict[str, Any]:
    data = await asyncio.to_thread(
        _blocking_get_json,
        f"https://paperswithcode.com/api/v1/papers/?arxiv_id={arxiv_id}",
        10.0,
    )
    entry: dict[str, Any] = {"github_url": None, "stars": 0, "at": time.time()}
    if not data:
        return entry
    result = (data.get("results") or [None])[0]
    if not result:
        return entry
    entry["github_url"] = result.get("github_url")
    rid = result.get("id")
    if rid:
        repo_data = await asyncio.to_thread(
            _blocking_get_json,
            f"https://paperswithcode.com/api/v1/paper/{rid}/repositories/",
            10.0,
        )
        results = (repo_data or {}).get("results") or []
        top = next((r for r in results if r.get("is_official")), results[0] if results else None)
        if top:
            entry["stars"] = top.get("stars") or 0
            entry["github_url"] = top.get("url") or entry["github_url"]
    return entry


@app.get("/api/pwc")
async def get_pwc(arxiv_ids: str):
    ids = [a.strip() for a in arxiv_ids.split(",") if a.strip()]
    now = time.time()

    missing = [a for a in ids if not (_pwc_cache.get(a) and now - _pwc_cache[a]["at"] < _PWC_TTL)]

    if missing:
        sem = asyncio.Semaphore(5)

        async def _bounded(aid: str):
            async with sem:
                _pwc_cache[aid] = await _fetch_pwc_one(aid)

        await asyncio.gather(*[_bounded(a) for a in missing])

    out = {}
    for a in ids:
        v = _pwc_cache.get(a)
        if v:
            out[a] = {"github_url": v["github_url"], "stars": v["stars"]}
    return {"results": out}


# ── HuggingFace Gemma 中文摘要 ────────────────────────────────────
_hf_client: InferenceClient | None = None
HF_TOKEN = os.environ.get("HF_TOKEN", "")
HF_MODEL = os.environ.get("HF_MODEL", "google/gemma-2-27b-it")
HF_PROVIDER = os.environ.get("HF_PROVIDER") or None

_SUMMARY_CACHE_MAX = 5000
_summary_cache: "OrderedDict[str, str]" = OrderedDict()


def _summary_cache_get(key: str) -> str | None:
    if key in _summary_cache:
        _summary_cache.move_to_end(key)
        return _summary_cache[key]
    return None


def _summary_cache_set(key: str, value: str) -> None:
    _summary_cache[key] = value
    _summary_cache.move_to_end(key)
    while len(_summary_cache) > _SUMMARY_CACHE_MAX:
        _summary_cache.popitem(last=False)


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

    cached = _summary_cache_get(req.arxiv_id)
    if cached is not None:
        return {"summary": cached}

    text = req.abstract[:2000]
    try:
        summary = await asyncio.to_thread(_blocking_summarize, text)
    except Exception as e:
        logger.error("summarize failed: %s", e)
        raise HTTPException(status_code=502, detail="summarization upstream failed")

    _summary_cache_set(req.arxiv_id, summary)
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
            statement_cache_size=0,  # Supabase transaction pooler 不支援 prepared statements
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
    data: dict


@app.put("/api/me/data")
async def put_my_data(body: UserDataPut, user: dict = Depends(_require_user)):
    import json as _json
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
            user["sub"], user.get("email"), user.get("name"), _json.dumps(body.data),
        )
    return {"ok": True}


@app.get("/api/me/config")
def get_auth_config():
    return {"google_client_id": GOOGLE_CLIENT_ID}
