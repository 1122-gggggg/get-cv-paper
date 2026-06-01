"""Upstream paper-source adapters: arXiv, HuggingFace daily, Semantic Scholar, Papers-with-Code.

Each function takes the shared httpx client and returns parsed Python data.
Transport / parse errors are translated into HTTP 502 (for hard upstream
failures) or empty / partial results (for soft failures), so handlers don't
re-implement try/except per upstream.
"""
from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any

import defusedxml.ElementTree as DET
import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

ARXIV_BASE = "https://export.arxiv.org/api/query"
ARXIV_UA = "Mozilla/5.0 DesktopDashboard/1.0"

_ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
_ARXIV_ID_RE = re.compile(r"\(arXiv:.*?\)")


# ── arXiv ─────────────────────────────────────────────────────────
_ARXIV_ID_NUM_RE = re.compile(r"(\d{4}\.\d{4,6})")


def _parse_arxiv_entries(xml_data: bytes, cutoff: datetime | None) -> list[dict[str, Any]]:
    root = DET.fromstring(xml_data)
    papers: list[dict[str, Any]] = []
    # arXiv 回應是 submittedDate desc;一旦遇到 cutoff 之前的可早停
    early_stop = cutoff is not None
    for entry in root.findall("atom:entry", _ARXIV_NS):
        title_el = entry.find("atom:title", _ARXIV_NS)
        id_el = entry.find("atom:id", _ARXIV_NS)
        if title_el is None or title_el.text is None or id_el is None:
            continue

        title = _ARXIV_ID_RE.sub("", title_el.text.strip().replace("\n", " ")).strip()

        summary_el = entry.find("atom:summary", _ARXIV_NS)
        summary = (
            summary_el.text.strip().replace("\n", " ")
            if summary_el is not None and summary_el.text
            else ""
        )

        pub_el = entry.find("atom:published", _ARXIV_NS)
        pub_raw = pub_el.text if pub_el is not None else ""
        try:
            pub_date = datetime.strptime(pub_raw, "%Y-%m-%dT%H:%M:%SZ")
            if cutoff is not None and pub_date < cutoff:
                if early_stop:
                    break
                continue
            published_str = pub_date.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            published_str = pub_raw

        authors = [
            a.find("atom:name", _ARXIV_NS).text  # type: ignore[union-attr]
            for a in entry.findall("atom:author", _ARXIV_NS)
            if a.find("atom:name", _ARXIV_NS) is not None
        ]

        arxiv_id = ""
        if id_el.text:
            m = _ARXIV_ID_NUM_RE.search(id_el.text)
            if m:
                arxiv_id = m.group(1)
        papers.append({
            "title": title,
            "summary": summary,
            "url": id_el.text,
            "published": published_str,
            "authors": authors,
            "source": "arxiv",
            "external_ids": {"arxiv": arxiv_id} if arxiv_id else {},
        })
    return papers


async def fetch_arxiv_listing(
    client: httpx.AsyncClient, cat: str, days: int, max_results: int,
    cats: list[str] | None = None, terms: str | None = None,
) -> list[dict[str, Any]]:
    # cats 為多分類 OR 查詢(如 ml = cs.LG OR stat.ML);terms 進一步以全文 AND 收窄(子主題用)
    cat_list = [c for c in (cats or [cat]) if c]
    cat_clause = " OR ".join(f"cat:{c}" for c in cat_list)
    if len(cat_list) > 1:
        cat_clause = f"({cat_clause})"
    search_query = f"{cat_clause} AND ({terms})" if terms else cat_clause
    label = "+".join(cat_list)
    params = {
        "search_query": search_query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    # arXiv 嚴格限流;遇 429/503 退避重試,避免整輪 warmup 把 IP 卡死
    delays = (3.0, 8.0, 0.0)  # 最後一次不再 sleep
    for attempt, sleep_s in enumerate(delays):
        try:
            r = await client.get(ARXIV_BASE, params=params, timeout=30.0)
            if r.status_code in (429, 503):
                if sleep_s > 0:
                    logger.info("arXiv %d on %s, retrying in %ss", r.status_code, label, sleep_s)
                    await asyncio.sleep(sleep_s)
                    continue
                raise HTTPException(status_code=502, detail="arXiv rate-limited")
            r.raise_for_status()
            break
        except HTTPException:
            raise
        except Exception as e:
            if attempt < len(delays) - 1:
                await asyncio.sleep(sleep_s or 2.0)
                continue
            logger.error("arXiv listing failed: %s", e)
            raise HTTPException(status_code=502, detail="arXiv upstream unavailable")
    cutoff = datetime.now() - timedelta(days=days)
    return _parse_arxiv_entries(r.content, cutoff)


async def fetch_arxiv_search(
    client: httpx.AsyncClient, q: str, max_results: int
) -> list[dict[str, Any]]:
    params = {
        "search_query": f"all:{q.strip()}",
        "sortBy": "relevance",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    try:
        r = await client.get(ARXIV_BASE, params=params, timeout=20.0)
        r.raise_for_status()
    except Exception as e:
        logger.error("arXiv search failed: %s", e)
        raise HTTPException(status_code=502, detail="arXiv upstream unavailable")
    return _parse_arxiv_entries(r.content, cutoff=None)


# ── HuggingFace daily papers ─────────────────────────────────────
async def fetch_hf_daily(client: httpx.AsyncClient, days: int = 7) -> list[dict[str, Any]]:
    try:
        r = await client.get("https://huggingface.co/api/daily_papers", timeout=15.0)
        if r.status_code != 200:
            return []
        raw = r.json()
    except Exception as e:
        logger.warning("HF daily fetch failed: %s", e)
        return []

    cutoff = datetime.now() - timedelta(days=days)
    papers: list[dict[str, Any]] = []
    for item in raw:
        paper = item.get("paper") or {}
        arxiv_id = paper.get("id") or ""
        if not arxiv_id:
            continue
        pub_raw = item.get("publishedAt") or paper.get("publishedAt") or ""
        try:
            pub_date = datetime.fromisoformat(pub_raw.replace("Z", "+00:00")).replace(tzinfo=None)
            if pub_date < cutoff:
                continue
            published_str = pub_date.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            published_str = pub_raw[:16].replace("T", " ")
        authors = [a.get("name", "") for a in (paper.get("authors") or []) if a.get("name")]
        papers.append({
            "title": (paper.get("title") or "").strip(),
            "summary": (paper.get("summary") or "").strip(),
            "url": f"http://arxiv.org/abs/{arxiv_id}",
            "published": published_str,
            "authors": authors,
            "source": "hf_daily",
            "hf_upvotes": item.get("upvotes") or paper.get("upvotes") or 0,
        })
    return papers


# ── Semantic Scholar ─────────────────────────────────────────────
_S2_URL = (
    "https://api.semanticscholar.org/graph/v1/paper/batch"
    "?fields=citationCount,influentialCitationCount,referenceCount,venue,publicationVenue"
)


async def fetch_s2_batch(
    client: httpx.AsyncClient, arxiv_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Returns {arxiv_id: {count, influential, refs, venue}} for the IDs we
    successfully resolved. Soft-fails on transport errors (returns partial)."""
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(arxiv_ids), 500):
        chunk = arxiv_ids[i : i + 500]
        try:
            r = await client.post(
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
            out[aid] = {
                "count": item.get("citationCount") or 0,
                "influential": item.get("influentialCitationCount") or 0,
                "refs": item.get("referenceCount") or 0,
                "venue": (item.get("publicationVenue") or {}).get("name")
                or item.get("venue")
                or "",
            }
    return out


# ── S2 paper search (作為 arXiv listing 的補強;按 fieldsOfStudy + query) ─────
_S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

# arXiv 主分類 → S2 fieldsOfStudy 映射(粗粒度)
_S2_FOS_PREFIX = (
    ("cs.",        "Computer Science"),
    ("stat.",      "Mathematics"),
    ("math.",      "Mathematics"),
    ("physics.",   "Physics"),
    ("astro-ph",   "Physics"),
    ("cond-mat",   "Physics"),
    ("hep-",       "Physics"),
    ("gr-qc",      "Physics"),
    ("nucl-",      "Physics"),
    ("quant-ph",   "Physics"),
    ("q-bio.",     "Biology"),
    ("q-fin.",     "Economics"),
    ("econ.",      "Economics"),
    ("eess.",      "Engineering"),
)


def s2_fos_for_cat(cat: str) -> str | None:
    if not cat:
        return None
    for prefix, fos in _S2_FOS_PREFIX:
        if cat.startswith(prefix) or cat == prefix.rstrip("."):
            return fos
    return None


async def fetch_s2_search(
    client: httpx.AsyncClient,
    query: str,
    fos: str | None,
    days: int,
    max_results: int,
) -> list[dict[str, Any]]:
    """以 query + fieldsOfStudy 搜近期論文;arXiv 限流時的第二來源。soft-fail。"""
    if not query:
        return []
    year = datetime.now().year
    params: dict[str, Any] = {
        "query": query,
        "fields": "title,abstract,year,authors,externalIds,publicationDate,venue,citationCount",
        "limit": min(max(max_results, 10), 100),
        "year": f"{year - 1}-{year}",
    }
    if fos:
        params["fieldsOfStudy"] = fos
    try:
        r = await client.get(_S2_SEARCH_URL, params=params, timeout=15.0)
        if r.status_code != 200:
            logger.warning("S2 search %s: %s", r.status_code, r.text[:200])
            return []
        data = r.json()
    except Exception as e:
        logger.warning("S2 search failed: %s", e)
        return []

    cutoff = datetime.now() - timedelta(days=days)
    out: list[dict[str, Any]] = []
    for p in data.get("data") or []:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        pub_raw = p.get("publicationDate") or ""
        try:
            pub_date = datetime.strptime(pub_raw, "%Y-%m-%d")
            if pub_date < cutoff:
                continue
            published_str = pub_date.strftime("%Y-%m-%d 00:00")
        except (ValueError, TypeError):
            # 缺日期就靠 year 過濾;保守接受當年的(去年的 cutoff 應已過濾)
            if p.get("year") and p["year"] < year:
                continue
            published_str = str(p.get("year") or "")
        ext_ids = p.get("externalIds") or {}
        arxiv_id = ext_ids.get("ArXiv") or ""
        doi = (ext_ids.get("DOI") or "").lower()
        url = (
            f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id
            else (f"https://doi.org/{doi}" if doi else (p.get("url") or ""))
        )
        out.append({
            "title": title,
            "summary": (p.get("abstract") or "").strip(),
            "url": url,
            "published": published_str,
            "authors": [a.get("name", "") for a in (p.get("authors") or []) if a.get("name")],
            "source": "s2_search",
            "external_ids": {**({"arxiv": arxiv_id} if arxiv_id else {}), **({"doi": doi} if doi else {})},
            "venue": p.get("venue") or "",
            "citation_count": p.get("citationCount") or 0,
        })
        if len(out) >= max_results:
            break
    return out


# ── OpenAlex (補 arXiv 沒涵蓋的學科,如人文社科/商管/純醫學) ──────
# Docs: https://docs.openalex.org/api-entities/works
# 免費免註冊。建議在 UA 帶 mailto 進 polite pool (response 較快)。
_OPENALEX_BASE = "https://api.openalex.org/works"
_OPENALEX_UA_MAILTO = "mailto:scholarly-dashboard@example.com"


def _abstract_from_inv_index(inv_index: dict[str, list[int]] | None) -> str:
    """OpenAlex 的 abstract 是 inverted index, 還原回原文"""
    if not inv_index:
        return ""
    # word -> positions; 還原成 list[(pos, word)]
    pairs: list[tuple[int, str]] = []
    for word, positions in inv_index.items():
        for p in positions:
            pairs.append((p, word))
    pairs.sort()
    return " ".join(w for _, w in pairs)


async def fetch_openalex_listing(
    client: httpx.AsyncClient,
    concept_id: str | None,
    days: int,
    max_results: int,
    search_query: str | None = None,
) -> list[dict[str, Any]]:
    """以 concept_id 篩學科, 或 search_query 模糊搜尋。"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    filters = [f"from_publication_date:{cutoff}"]
    if concept_id:
        filters.append(f"concepts.id:{concept_id}")
    params: dict[str, Any] = {
        "filter": ",".join(filters),
        "sort": "publication_date:desc",
        "per-page": min(max_results, 200),  # OpenAlex 上限 200
        "mailto": "scholarly-dashboard@example.com",
    }
    if search_query:
        params["search"] = search_query

    try:
        r = await client.get(_OPENALEX_BASE, params=params, timeout=20.0)
        if r.status_code != 200:
            logger.warning("OpenAlex %s: %s", r.status_code, r.text[:200])
            return []
        data = r.json()
    except Exception as e:
        logger.warning("OpenAlex fetch failed: %s", e)
        return []

    out: list[dict[str, Any]] = []
    for w in data.get("results", []) or []:
        title = (w.get("title") or w.get("display_name") or "").strip()
        if not title:
            continue
        # 篩出 abstract
        summary = _abstract_from_inv_index(w.get("abstract_inverted_index"))
        # 作者
        authors = [
            (auth.get("author") or {}).get("display_name", "")
            for auth in (w.get("authorships") or [])
            if (auth.get("author") or {}).get("display_name")
        ]
        # external_ids
        ids = w.get("ids") or {}
        doi = ids.get("doi")
        if doi:
            doi = doi.replace("https://doi.org/", "")
        # arXiv 重複偵測:OpenAlex 有些 work 來源就是 arXiv
        arxiv_id = ""
        for loc in (w.get("locations") or []):
            src = (loc.get("source") or {})
            if (src.get("display_name") or "").lower() == "arxiv":
                landing = loc.get("landing_page_url") or ""
                m = re.search(r"(\d{4}\.\d{4,6})", landing)
                if m:
                    arxiv_id = m.group(1)
                    break
        ext = {}
        if doi: ext["doi"] = doi
        if arxiv_id: ext["arxiv"] = arxiv_id
        # primary url: arXiv 優先, 否則 doi.org
        url = (
            f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id
            else (f"https://doi.org/{doi}" if doi else (w.get("doi") or w.get("id") or ""))
        )
        # venue
        venue = ""
        host = (w.get("primary_location") or {}).get("source") or {}
        if host.get("display_name"):
            venue = host["display_name"]
        # published date
        pub = w.get("publication_date") or ""
        try:
            pub_date = datetime.strptime(pub, "%Y-%m-%d")
            published_str = pub_date.strftime("%Y-%m-%d 00:00")
        except (ValueError, TypeError):
            published_str = pub

        out.append({
            "title": title,
            "summary": summary,
            "url": url,
            "published": published_str,
            "authors": authors,
            "source": "openalex",
            "external_ids": ext,
            "venue": venue,
            "citation_count": w.get("cited_by_count") or 0,
        })
    return out


# ── Crossref (期刊論文 metadata; 補 IEEE/Springer/Elsevier) ─────
# Docs: https://api.crossref.org/swagger-ui/index.html
# 免費,放 mailto 進 polite pool。filter 用 from-pub-date / type=journal-article
_CROSSREF_BASE = "https://api.crossref.org/works"


async def fetch_crossref_listing(
    client: httpx.AsyncClient,
    subject: str | None,
    days: int,
    max_results: int,
    search_query: str | None = None,
) -> list[dict[str, Any]]:
    """以 subject 過濾學科,或 query 模糊搜尋。回 journal-article only。"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    filters = [f"from-pub-date:{cutoff}", "type:journal-article"]
    params: dict[str, Any] = {
        "filter": ",".join(filters),
        "rows": min(max_results, 200),
        "sort": "published",
        "order": "desc",
        "mailto": "scholarly-dashboard@example.com",
    }
    if search_query:
        params["query"] = search_query
    if subject:
        # crossref subject 是文字 (e.g., "Computer Science"); 用 query.bibliographic 較穩
        params["query.bibliographic"] = subject

    try:
        r = await client.get(_CROSSREF_BASE, params=params, timeout=20.0)
        if r.status_code != 200:
            logger.warning("Crossref %s: %s", r.status_code, r.text[:200])
            return []
        data = r.json()
    except Exception as e:
        logger.warning("Crossref fetch failed: %s", e)
        return []

    out: list[dict[str, Any]] = []
    for w in (data.get("message") or {}).get("items", []) or []:
        title_list = w.get("title") or []
        title = (title_list[0] if title_list else "").strip()
        if not title:
            continue
        doi = (w.get("DOI") or "").strip().lower()
        # date: published-online > published-print > issued
        date_parts = None
        for k in ("published-online", "published-print", "issued"):
            v = w.get(k)
            if v and v.get("date-parts"):
                date_parts = v["date-parts"][0]
                break
        if date_parts and len(date_parts) >= 1:
            y = date_parts[0]
            m = date_parts[1] if len(date_parts) > 1 else 1
            d = date_parts[2] if len(date_parts) > 2 else 1
            published_str = f"{y:04d}-{m:02d}-{d:02d} 00:00"
        else:
            published_str = ""
        authors = []
        for a in (w.get("author") or []):
            name = ((a.get("given") or "") + " " + (a.get("family") or "")).strip()
            if name:
                authors.append(name)
        # venue: container-title
        ct = w.get("container-title") or []
        venue = ct[0] if ct else ""
        summary = (w.get("abstract") or "").strip()
        # crossref abstract 常包 jats:p tag,粗暴去掉
        if summary:
            summary = re.sub(r"<[^>]+>", "", summary)
        ext: dict[str, str] = {}
        if doi:
            ext["doi"] = doi
        out.append({
            "title": title,
            "summary": summary,
            "url": f"https://doi.org/{doi}" if doi else (w.get("URL") or ""),
            "published": published_str,
            "authors": authors,
            "source": "crossref",
            "external_ids": ext,
            "venue": venue,
            "citation_count": w.get("is-referenced-by-count") or 0,
        })
    return out


# ── bioRxiv / medRxiv (生命科學 / 醫學預印本) ──────────────────
# Docs: https://api.biorxiv.org/  (免註冊)
# Endpoint: /details/{server}/{interval}/{cursor}
_BIORXIV_BASE = "https://api.biorxiv.org/details"


async def fetch_biorxiv_listing(
    client: httpx.AsyncClient,
    server: str,  # "biorxiv" or "medrxiv"
    days: int,
    max_results: int,
) -> list[dict[str, Any]]:
    """server in {biorxiv, medrxiv}。biorxiv 一次最多回 100 筆,需翻頁。"""
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    out: list[dict[str, Any]] = []
    cursor = 0
    while len(out) < max_results:
        url = f"{_BIORXIV_BASE}/{server}/{start}/{end}/{cursor}"
        try:
            r = await client.get(url, timeout=20.0)
            if r.status_code != 200:
                break
            data = r.json()
        except Exception as e:
            logger.warning("%s fetch failed: %s", server, e)
            break
        items = data.get("collection") or []
        if not items:
            break
        for it in items:
            title = (it.get("title") or "").strip()
            if not title:
                continue
            doi = (it.get("doi") or "").strip().lower()
            authors_raw = it.get("authors") or ""
            # bioRxiv author 形式: "Last, F.; Last2, F2."
            authors = [a.strip() for a in re.split(r"[;]", authors_raw) if a.strip()]
            published_str = (it.get("date") or "") + " 00:00" if it.get("date") else ""
            ext: dict[str, str] = {}
            if doi:
                ext["doi"] = doi
            out.append({
                "title": title,
                "summary": (it.get("abstract") or "").strip(),
                "url": f"https://doi.org/{doi}" if doi else "",
                "published": published_str,
                "authors": authors,
                "source": server,  # "biorxiv" or "medrxiv"
                "external_ids": ext,
                "venue": server,
            })
            if len(out) >= max_results:
                break
        # bioRxiv 一次回 100,以 collection 長度判斷是否有下一頁
        if len(items) < 100:
            break
        cursor += len(items)
        if cursor > 500:  # 上限保護
            break
    return out


# ── PubMed E-utilities (醫學/藥學/神經科學) ────────────────────
# Docs: https://www.ncbi.nlm.nih.gov/books/NBK25500/
# 免費,但每秒 ≤3 req (沒 API key 的限制),所以加 token bucket。
_PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_PUBMED_LOCK = asyncio.Lock()
_PUBMED_LAST_TS: list[float] = [0.0, 0.0, 0.0]  # 最近 3 次 request 時間


async def _pubmed_throttle() -> None:
    """3 req/sec token bucket (滑動窗)"""
    import time as _t
    async with _PUBMED_LOCK:
        now = _t.time()
        oldest = _PUBMED_LAST_TS[0]
        if now - oldest < 1.0:
            await asyncio.sleep(1.0 - (now - oldest) + 0.05)
        _PUBMED_LAST_TS.pop(0)
        _PUBMED_LAST_TS.append(_t.time())


async def fetch_pubmed_listing(
    client: httpx.AsyncClient,
    mesh_term: str | None,
    days: int,
    max_results: int,
) -> list[dict[str, Any]]:
    """兩段式: esearch 拿 PMID -> efetch 拿 metadata。"""
    if not mesh_term:
        return []
    term = f'{mesh_term}[MeSH Terms] AND "last {days} days"[dp]'
    # esearch
    await _pubmed_throttle()
    try:
        r1 = await client.get(_PUBMED_ESEARCH, params={
            "db": "pubmed", "term": term, "retmode": "json",
            "retmax": min(max_results, 200), "sort": "pub_date",
            "tool": "scholarly-dashboard", "email": "scholarly-dashboard@example.com",
        }, timeout=15.0)
        if r1.status_code != 200:
            return []
        ids = (r1.json().get("esearchresult") or {}).get("idlist") or []
    except Exception as e:
        logger.warning("PubMed esearch failed: %s", e)
        return []
    if not ids:
        return []

    # efetch (XML)
    await _pubmed_throttle()
    try:
        r2 = await client.get(_PUBMED_EFETCH, params={
            "db": "pubmed", "id": ",".join(ids), "retmode": "xml",
            "tool": "scholarly-dashboard", "email": "scholarly-dashboard@example.com",
        }, timeout=20.0)
        if r2.status_code != 200:
            return []
        # PubMed efetch XML relies on externally-defined entities; defusedxml's
        # forbid_external would reject them. Upstream is NCBI (trusted) and this path is
        # entity-bomb-free, so stdlib ET is intentional here (arXiv Atom uses DET above).
        root = ET.fromstring(r2.content)
    except Exception as e:
        logger.warning("PubMed efetch failed: %s", e)
        return []

    out: list[dict[str, Any]] = []
    for art in root.findall(".//PubmedArticle"):
        title_el = art.find(".//ArticleTitle")
        title = (title_el.text or "").strip() if title_el is not None and title_el.text else ""
        if not title:
            continue
        # abstract (可能多段 AbstractText)
        abst_parts = []
        for ab in art.findall(".//Abstract/AbstractText"):
            if ab.text:
                abst_parts.append(ab.text.strip())
        summary = " ".join(abst_parts)
        # PMID
        pmid_el = art.find(".//PMID")
        pmid = pmid_el.text if pmid_el is not None and pmid_el.text else ""
        # DOI (多個 ArticleId, 抓 IdType=doi)
        doi = ""
        for aid in art.findall(".//ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi" and aid.text:
                doi = aid.text.strip().lower()
                break
        # date
        published_str = ""
        d_el = art.find(".//PubDate")
        if d_el is not None:
            y = (d_el.findtext("Year") or "")
            m = (d_el.findtext("Month") or "01")
            day = (d_el.findtext("Day") or "01")
            month_map = {"Jan":"01","Feb":"02","Mar":"03","Apr":"04","May":"05","Jun":"06",
                         "Jul":"07","Aug":"08","Sep":"09","Oct":"10","Nov":"11","Dec":"12"}
            m = month_map.get(m, m)
            try:
                published_str = f"{int(y):04d}-{int(m):02d}-{int(day):02d} 00:00"
            except (ValueError, TypeError):
                published_str = y
        # authors
        authors = []
        for a in art.findall(".//AuthorList/Author"):
            fn = a.findtext("ForeName") or ""
            ln = a.findtext("LastName") or ""
            full = f"{fn} {ln}".strip()
            if full:
                authors.append(full)
        # venue
        venue = (art.findtext(".//Journal/Title") or "").strip()
        ext: dict[str, str] = {}
        if doi: ext["doi"] = doi
        if pmid: ext["pmid"] = pmid
        url = (
            f"https://doi.org/{doi}" if doi
            else (f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "")
        )
        out.append({
            "title": title,
            "summary": summary,
            "url": url,
            "published": published_str,
            "authors": authors,
            "source": "pubmed",
            "external_ids": ext,
            "venue": venue,
        })
    return out


# ── DBLP (CS 會議/期刊 metadata; 補強 venue 用,不獨立顯示) ──────
# Docs: https://dblp.org/faq/13501473.html
# 純 metadata source,沒 abstract,所以做 venue lookup adapter
_DBLP_PUB_API = "https://dblp.org/search/publ/api"


async def fetch_dblp_venue(
    client: httpx.AsyncClient, title: str
) -> str | None:
    """以 title 查 DBLP, 回傳第一個命中的 venue (CS 頂會用)。soft-fail。"""
    if not title or len(title) < 8:
        return None
    try:
        r = await client.get(_DBLP_PUB_API, params={
            "q": title, "format": "json", "h": 1,
        }, timeout=8.0)
        if r.status_code != 200:
            return None
        hits = (((r.json() or {}).get("result") or {}).get("hits") or {}).get("hit") or []
        if not hits:
            return None
        info = hits[0].get("info") or {}
        return info.get("venue") or None
    except Exception:
        return None


async def fetch_dblp_venues_many(
    client: httpx.AsyncClient, titles: list[str], concurrency: int = 4
) -> dict[str, str]:
    """批次 venue 查詢 (DBLP 沒 batch API,自己 gather)。"""
    sem = asyncio.Semaphore(concurrency)
    out: dict[str, str] = {}

    async def _one(t: str) -> None:
        async with sem:
            v = await fetch_dblp_venue(client, t)
            if v:
                out[t] = v

    await asyncio.gather(*[_one(t) for t in titles])
    return out


# ── OpenReview (ICLR / NeurIPS / ICML 投稿 + 公開評審) ──────────
# Docs: https://docs.openreview.net/getting-started/using-the-api
# 使用 v2 API,無需登入即可拿公開 metadata + 評審分數。
_OPENREVIEW_BASE = "https://api2.openreview.net/notes"

_OPENREVIEW_VENUE_GROUPS = {
    "iclr": "ICLR.cc",
    "neurips": "NeurIPS.cc",
    "icml": "ICML.cc",
    "colm": "COLM",
}
# review 分數欄位名各 venue/年度不一,依序試;值可能是 int 或 "6: marginally above..."
_OPENREVIEW_RATING_FIELDS = ("rating", "recommendation", "overall_rating", "review_rating")
_OPENREVIEW_RATING_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _parse_or_rating(value: Any) -> float | None:
    """OpenReview 評審分數正規化:int/float 直取,字串取開頭數字('6: ...' → 6)。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = _OPENREVIEW_RATING_RE.search(value)
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return None
    return None


def _openreview_ratings(note: dict[str, Any]) -> list[float]:
    """從一篇 submission 的 directReplies 抽出所有 official review 分數。"""
    replies = (note.get("details") or {}).get("directReplies") or []
    ratings: list[float] = []
    for reply in replies:
        content = reply.get("content") or {}
        for field in _OPENREVIEW_RATING_FIELDS:
            raw = content.get(field)
            if isinstance(raw, dict):
                raw = raw.get("value")
            score = _parse_or_rating(raw)
            if score is not None:
                ratings.append(score)
                break
    return ratings


async def fetch_openreview_listing(
    client: httpx.AsyncClient,
    venue: str,            # "iclr" | "neurips" | "icml" | "colm"
    year: int | None = None,
    days: int = 30,
    max_results: int = 200,
) -> list[dict[str, Any]]:
    """從 OpenReview 抓某 venue 該年的所有 submission 與評審分數。

    回應正規化成跟其他源一致的 paper dict;額外帶 review_avg / review_count。
    soft-fail。
    """
    group = _OPENREVIEW_VENUE_GROUPS.get(venue.lower())
    if not group:
        return []
    if year is None:
        year = datetime.now().year

    params = {
        # v2 用 venueid(group path)而非 venue(人類可讀字串);後者查不到任何 note
        "content.venueid": f"{group}/{year}/Conference",
        "details": "directReplies",  # 內嵌評審 reply,供解析 review_avg/review_count
        "limit": min(max_results, 1000),
    }
    try:
        r = await client.get(_OPENREVIEW_BASE, params=params, timeout=20.0)
        if r.status_code != 200:
            logger.warning("OpenReview %s/%s: %s", venue, year, r.status_code)
            return []
        data = r.json()
    except Exception as e:
        logger.warning("OpenReview %s fetch failed: %s", venue, e)
        return []

    cutoff_ms = (datetime.now() - timedelta(days=days)).timestamp() * 1000
    out: list[dict[str, Any]] = []
    for note in data.get("notes", []) or []:
        cdate = note.get("cdate") or 0
        if cdate < cutoff_ms:
            continue
        content = note.get("content") or {}
        # OpenReview v2 content 是 {field: {value: X}}
        def _v(k: str) -> Any:
            f = content.get(k)
            if isinstance(f, dict):
                return f.get("value")
            return f

        title = (_v("title") or "").strip()
        if not title:
            continue
        abstract = (_v("abstract") or "").strip()
        authors = _v("authors") or []
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(",") if a.strip()]
        # cdate ms epoch → date
        try:
            pub_dt = datetime.fromtimestamp(cdate / 1000)
            published_str = pub_dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError, OSError):
            published_str = ""
        # 嘗試找 arXiv link (在 _bibtex 或 pdf url)
        arxiv_id = ""
        for v in (_v("_bibtex"), _v("pdf"), _v("html")):
            if v and isinstance(v, str):
                m = _ARXIV_ID_NUM_RE.search(v)
                if m:
                    arxiv_id = m.group(1)
                    break
        ext: dict[str, str] = {"openreview": note.get("id", "")}
        if arxiv_id:
            ext["arxiv"] = arxiv_id

        forum_id = note.get("forum") or note.get("id") or ""
        paper: dict[str, Any] = {
            "title": title,
            "summary": abstract,
            "url": f"https://openreview.net/forum?id={forum_id}",
            "published": published_str,
            "authors": [a for a in authors if a],
            "source": "openreview",
            "external_ids": ext,
            "venue": f"{venue.upper()} {year}",
        }
        ratings = _openreview_ratings(note)
        if ratings:
            avg = round(sum(ratings) / len(ratings), 1)
            paper["review_avg"] = avg
            paper["review_count"] = len(ratings)
            paper["or_rating"] = avg  # 前端 badge 既有 or_rating 路徑
        out.append(paper)
        if len(out) >= max_results:
            break
    # 已評審的排前面、分數高的優先;未評審投稿維持其後
    out.sort(key=lambda p: p.get("review_avg") or -1.0, reverse=True)
    return out


# ── Semantic Scholar 擴展:推薦 / 作者 / 引用歷史 ──────────────
async def fetch_s2_recommendations(
    client: httpx.AsyncClient, arxiv_id: str, limit: int = 10
) -> list[dict[str, Any]]:
    """以一篇 arXiv 為 seed,回傳 S2 推薦的相似論文。soft-fail。"""
    url = (
        f"https://api.semanticscholar.org/recommendations/v1/papers/forpaper/"
        f"ArXiv:{arxiv_id}"
    )
    params = {
        "fields": "title,abstract,year,authors,externalIds,venue,citationCount",
        "limit": min(limit, 100),
    }
    try:
        r = await client.get(url, params=params, timeout=15.0)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception as e:
        logger.warning("S2 recommendations failed: %s", e)
        return []

    out: list[dict[str, Any]] = []
    for p in data.get("recommendedPapers") or []:
        ext_ids = p.get("externalIds") or {}
        aid = ext_ids.get("ArXiv") or ""
        doi = (ext_ids.get("DOI") or "").lower()
        url2 = (
            f"https://arxiv.org/abs/{aid}" if aid
            else (f"https://doi.org/{doi}" if doi else "")
        )
        out.append({
            "title": (p.get("title") or "").strip(),
            "summary": (p.get("abstract") or "").strip(),
            "url": url2,
            "published": str(p.get("year") or ""),
            "authors": [a.get("name", "") for a in (p.get("authors") or []) if a.get("name")],
            "source": "s2_rec",
            "external_ids": {**({"arxiv": aid} if aid else {}), **({"doi": doi} if doi else {})},
            "venue": p.get("venue") or "",
            "citation_count": p.get("citationCount") or 0,
        })
    return out


async def fetch_s2_author_papers(
    client: httpx.AsyncClient, author_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    """抓某作者的近期論文。author_id 是 S2 內部 ID。soft-fail。"""
    url = f"https://api.semanticscholar.org/graph/v1/author/{author_id}/papers"
    params = {
        "fields": "title,abstract,year,publicationDate,externalIds,venue,citationCount",
        "limit": min(limit, 100),
    }
    try:
        r = await client.get(url, params=params, timeout=15.0)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception as e:
        logger.warning("S2 author papers failed: %s", e)
        return []

    out: list[dict[str, Any]] = []
    for p in data.get("data") or []:
        ext_ids = p.get("externalIds") or {}
        aid = ext_ids.get("ArXiv") or ""
        doi = (ext_ids.get("DOI") or "").lower()
        url2 = (
            f"https://arxiv.org/abs/{aid}" if aid
            else (f"https://doi.org/{doi}" if doi else "")
        )
        out.append({
            "title": (p.get("title") or "").strip(),
            "summary": (p.get("abstract") or "").strip(),
            "url": url2,
            "published": p.get("publicationDate") or str(p.get("year") or ""),
            "authors": [],  # author endpoint 不回 co-author list
            "source": "s2_author",
            "external_ids": {**({"arxiv": aid} if aid else {}), **({"doi": doi} if doi else {})},
            "venue": p.get("venue") or "",
            "citation_count": p.get("citationCount") or 0,
        })
    return out


async def fetch_s2_author_search(
    client: httpx.AsyncClient, name: str, limit: int = 5
) -> list[dict[str, Any]]:
    """name → 候選 S2 author。soft-fail。"""
    url = "https://api.semanticscholar.org/graph/v1/author/search"
    params = {
        "query": name,
        "fields": "name,affiliations,paperCount,citationCount,hIndex",
        "limit": min(limit, 100),
    }
    try:
        r = await client.get(url, params=params, timeout=10.0)
        if r.status_code != 200:
            return []
        return (r.json().get("data") or [])
    except Exception as e:
        logger.warning("S2 author search failed: %s", e)
        return []


# ── Papers with Code ─────────────────────────────────────────────
async def fetch_pwc_one(client: httpx.AsyncClient, arxiv_id: str) -> dict[str, Any]:
    entry: dict[str, Any] = {"github_url": None, "stars": 0}
    try:
        r = await client.get(
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
    if not rid:
        return entry
    try:
        r2 = await client.get(
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


async def fetch_pwc_many(
    client: httpx.AsyncClient, arxiv_ids: list[str], concurrency: int = 5
) -> dict[str, dict[str, Any]]:
    sem = asyncio.Semaphore(concurrency)
    out: dict[str, dict[str, Any]] = {}

    async def _one(aid: str) -> None:
        async with sem:
            out[aid] = await fetch_pwc_one(client, aid)

    await asyncio.gather(*[_one(a) for a in arxiv_ids])
    return out


# ── GitHub stars (PwC 已於 2025-07 關閉,改直接打 GitHub API) ────────
GITHUB_API = "https://api.github.com"
_GITHUB_URL_RE = re.compile(
    r"https?://github\.com/([A-Za-z0-9][\w.-]*)/([A-Za-z0-9][\w.-]*?)(?:\.git)?(?=[\s)\].,;'\"<]|$)",
    re.IGNORECASE,
)
_GITHUB_BAD_OWNERS = {"sponsors", "about", "features", "topics", "collections", "marketplace"}


def extract_github_url(text: str | None) -> str | None:
    """從摘要抓第一個 github repo URL(owner/repo),濾掉非 repo 路徑。"""
    if not text:
        return None
    for owner, repo in _GITHUB_URL_RE.findall(text):
        if owner.lower() in _GITHUB_BAD_OWNERS:
            continue
        repo = repo.rstrip(".")
        if not repo:
            continue
        return f"https://github.com/{owner}/{repo}"
    return None


def github_repo_slug(github_url: str | None) -> str | None:
    """https://github.com/owner/repo → 'owner/repo'(供 GitHub API 用)。"""
    if not github_url:
        return None
    m = _GITHUB_URL_RE.search(github_url)
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2).rstrip('.')}"


async def fetch_github_stars(
    client: httpx.AsyncClient,
    repo_slugs: list[str],
    token: str | None = None,
    concurrency: int = 4,
) -> dict[str, int]:
    """批次查詢 repo star 數。回傳 {slug: stars};查不到的 slug 省略。

    有 token → 5000 req/hr;無 token → 60 req/hr,呼叫端需自行控管預算。
    """
    if not repo_slugs:
        return {}
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": ARXIV_UA,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    sem = asyncio.Semaphore(concurrency)
    out: dict[str, int] = {}

    async def _one(slug: str) -> None:
        async with sem:
            try:
                r = await client.get(f"{GITHUB_API}/repos/{slug}", headers=headers, timeout=10.0)
                if r.status_code == 200:
                    stars = r.json().get("stargazers_count")
                    if isinstance(stars, int):
                        out[slug] = stars
                elif r.status_code == 403 and "rate limit" in (r.text or "").lower():
                    logger.warning("GitHub rate-limited on %s", slug)
            except Exception as e:
                logger.debug("GitHub stars fetch failed for %s: %s", slug, e)

    await asyncio.gather(*[_one(s) for s in dict.fromkeys(repo_slugs)])
    return out
