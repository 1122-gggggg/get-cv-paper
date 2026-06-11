"""arXiv OAI-PMH incremental harvester.

The Atom query API (clients.fetch_arxiv_listing) caps results per request, so on
high-volume archives (cs) it silently drops recently-announced papers. OAI-PMH
ListRecords returns the *complete* set for a datestamp window via resumption
tokens, letting us top-up the L2 PaperStore so recent coverage is exhaustive
rather than truncated.

Bounded by design for a free-tier VM: harvests only the delta since the last
stored datestamp, capped by max_pages / max_records per run, with 503/Retry-After
backoff. parse_oai_records is a pure function (offline-testable).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import defusedxml.ElementTree as DET
import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

OAI_BASE = "https://export.arxiv.org/oai2"
OAI_UA = "Mozilla/5.0 DesktopDashboard/1.0"

_OAI_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "arxiv": "http://arxiv.org/OAI/arXiv/",
}

# arXiv OAI setSpec is archive-level (cs, math, stat, ...); physics archives are
# grouped (physics:cond-mat). Map a discipline's arXiv category → its OAI set.
_PHYSICS_GROUPS = {
    "cond-mat": "physics:cond-mat",
    "astro-ph": "physics:astro-ph",
    "gr-qc": "physics:gr-qc",
    "hep-ex": "physics:hep-ex",
    "hep-lat": "physics:hep-lat",
    "hep-ph": "physics:hep-ph",
    "hep-th": "physics:hep-th",
    "math-ph": "physics:math-ph",
    "nlin": "physics:nlin",
    "nucl-ex": "physics:nucl-ex",
    "nucl-th": "physics:nucl-th",
    "quant-ph": "physics:quant-ph",
    "physics": "physics:physics",
}


def cat_to_oai_set(cat: str) -> str | None:
    """Map an arXiv category (cs.CV, cond-mat.stat-mech, hep-th) to its OAI set."""
    if not cat:
        return None
    archive = cat.split(".", 1)[0]
    if archive in ("cs", "math", "stat", "eess", "econ", "q-bio", "q-fin"):
        return archive
    return _PHYSICS_GROUPS.get(archive)


def _author_name(author: Any) -> str:
    keyname = author.findtext("arxiv:keyname", default="", namespaces=_OAI_NS).strip()
    forenames = author.findtext("arxiv:forenames", default="", namespaces=_OAI_NS).strip()
    name = f"{forenames} {keyname}".strip()
    return name


def parse_oai_records(xml_data: bytes) -> tuple[list[dict[str, Any]], str | None]:
    """Parse one OAI ListRecords page → (papers, resumption_token).

    resumption_token is None when the list is complete (or on noRecordsMatch).
    Deleted-record headers and metadata-less records are skipped. Each paper
    mirrors the clients._parse_arxiv_entries shape plus a `categories` list.
    """
    root = DET.fromstring(xml_data)

    err = root.find("oai:error", _OAI_NS)
    if err is not None:
        code = (err.get("code") or "").strip()
        if code == "noRecordsMatch":
            return [], None
        raise HTTPException(status_code=502, detail=f"arXiv OAI error: {code or 'unknown'}")

    list_el = root.find("oai:ListRecords", _OAI_NS)
    if list_el is None:
        return [], None

    papers: list[dict[str, Any]] = []
    for record in list_el.findall("oai:record", _OAI_NS):
        header = record.find("oai:header", _OAI_NS)
        if header is not None and (header.get("status") or "").strip() == "deleted":
            continue
        meta = record.find("oai:metadata/arxiv:arXiv", _OAI_NS)
        if meta is None:
            continue

        arxiv_id = meta.findtext("arxiv:id", default="", namespaces=_OAI_NS).strip()
        title = meta.findtext("arxiv:title", default="", namespaces=_OAI_NS)
        if not arxiv_id or not title:
            continue
        title = " ".join(title.split())

        abstract = meta.findtext("arxiv:abstract", default="", namespaces=_OAI_NS)
        summary = " ".join(abstract.split())

        created = meta.findtext("arxiv:created", default="", namespaces=_OAI_NS).strip()
        updated = meta.findtext("arxiv:updated", default="", namespaces=_OAI_NS).strip()
        day = created or updated
        published = f"{day} 00:00" if day else ""

        authors = [
            n for a in meta.findall("arxiv:authors/arxiv:author", _OAI_NS)
            if (n := _author_name(a))
        ]
        cats_raw = meta.findtext("arxiv:categories", default="", namespaces=_OAI_NS)
        categories = [c for c in cats_raw.split() if c]

        papers.append({
            "title": title,
            "summary": summary,
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "published": published,
            "authors": authors,
            "source": "arxiv",
            "external_ids": {"arxiv": arxiv_id},
            "categories": categories,
        })

    token_el = list_el.find("oai:resumptionToken", _OAI_NS)
    token = token_el.text.strip() if token_el is not None and token_el.text else None
    return papers, (token or None)


async def _oai_fetch_page(
    client: httpx.AsyncClient, params: dict[str, str], label: str
) -> bytes:
    """One OAI request with 503/Retry-After backoff. Raises HTTPException on failure."""
    delays = (5.0, 15.0, 0.0)  # last attempt does not sleep
    for attempt, fallback in enumerate(delays):
        try:
            r = await client.get(
                OAI_BASE, params=params, timeout=40.0, headers={"User-Agent": OAI_UA}
            )
            if r.status_code == 503:
                if fallback <= 0:
                    raise HTTPException(status_code=502, detail="arXiv OAI rate-limited")
                wait = fallback
                try:
                    wait = min(60.0, float(r.headers.get("Retry-After", fallback)))
                except (TypeError, ValueError):
                    wait = fallback
                logger.info("OAI 503 on %s, retrying in %ss", label, wait)
                await asyncio.sleep(wait)
                continue
            r.raise_for_status()
            return r.content
        except HTTPException:
            raise
        except Exception as e:
            if attempt < len(delays) - 1:
                await asyncio.sleep(fallback or 5.0)
                continue
            logger.error("OAI fetch failed for %s: %s", label, e)
            raise HTTPException(status_code=502, detail="arXiv OAI unavailable") from e
    raise HTTPException(status_code=502, detail="arXiv OAI unavailable")


async def harvest_arxiv_oai(
    client: httpx.AsyncClient,
    oai_set: str,
    *,
    from_date: str,
    max_pages: int = 4,
    max_records: int = 4000,
) -> list[dict[str, Any]]:
    """Incrementally harvest an OAI set from `from_date` (YYYY-MM-DD), inclusive.

    Follows resumption tokens up to max_pages, bounded by max_records total.
    Returns deduped paper dicts (parse_oai_records shape). Soft-fails to whatever
    was collected if a later page errors mid-pagination.
    """
    params = {
        "verb": "ListRecords",
        "metadataPrefix": "arXiv",
        "set": oai_set,
        "from": from_date,
    }
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    token: str | None = None

    for page in range(max_pages):
        if token:
            params = {"verb": "ListRecords", "resumptionToken": token}
        try:
            content = await _oai_fetch_page(client, params, f"{oai_set}@{from_date}")
            papers, token = parse_oai_records(content)
        except HTTPException:
            if page == 0:
                raise
            logger.warning("OAI %s: stopping at page %d on upstream error", oai_set, page)
            break
        for p in papers:
            pid = p["external_ids"].get("arxiv", "")
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            collected.append(p)
            if len(collected) >= max_records:
                logger.info("OAI %s: hit max_records cap %d", oai_set, max_records)
                return collected
        if not token:
            break
    return collected
