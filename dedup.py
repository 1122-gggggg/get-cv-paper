"""跨來源論文去重 + 合併。

3 層 key (依優先級):
  1. DOI 完全比對 (規範化)
  2. arXiv ID 比對
  3. Fuzzy title + first author lastname

來源優先級 (誰留下、誰被丟棄):
  arxiv > openalex > crossref > pubmed > biorxiv > medrxiv > dblp

合併規則:
  - source 變成 list, 累積所有命中過的來源
  - external_ids 合併 dict (arXiv ID / DOI / PMID)
  - citation count 取 max
  - hf_upvotes 只 arXiv 來源有,直接保留
  - title/summary 取主來源 (優先級高的)
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

# 來源優先級 (數字越小越優先,留主紀錄)
SOURCE_PRIORITY = {
    "arxiv":    0,
    "hf_daily": 0,   # HF Daily 本質是 arXiv 子集, 視為同等
    "openalex": 1,
    "crossref": 2,
    "pubmed":   3,
    "biorxiv":  4,
    "medrxiv":  4,
    "dblp":     5,
}

_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,6})(v\d+)?")
_DOI_RE = re.compile(r"10\.\d{4,9}/[\-._;()/:A-Za-z0-9]+", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def _normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip().lower()
    # 去掉常見前綴
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    doi = doi.rstrip("/")
    return doi if _DOI_RE.fullmatch(doi) else None


def _extract_arxiv_id(paper: dict[str, Any]) -> str | None:
    ext = paper.get("external_ids") or {}
    if ext.get("arxiv"):
        m = _ARXIV_ID_RE.search(str(ext["arxiv"]))
        if m:
            return m.group(1)
    url = paper.get("url") or ""
    m = _ARXIV_ID_RE.search(url)
    return m.group(1) if m else None


def _extract_doi(paper: dict[str, Any]) -> str | None:
    ext = paper.get("external_ids") or {}
    doi = _normalize_doi(ext.get("doi"))
    if doi:
        return doi
    # 在 url 裡掃 DOI (Crossref / OpenAlex 常 url 就是 doi.org/...)
    url = paper.get("url") or ""
    m = _DOI_RE.search(url)
    return _normalize_doi(m.group(0)) if m else None


def _fuzzy_title_key(title: str | None, authors: list[str] | None) -> str | None:
    """標題 lowercase + 去標點 + 取前 60 字 + 第一作者 lastname"""
    if not title:
        return None
    t = unicodedata.normalize("NFKD", title).lower()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()[:60]
    if not t:
        return None
    first_last = ""
    if authors:
        first = (authors[0] or "").strip()
        if first:
            # 取最後一個 token 當 lastname (處理 "First Last" / "Last, First")
            if "," in first:
                first_last = first.split(",")[0].strip().lower()
            else:
                first_last = first.split()[-1].lower() if first.split() else ""
    return f"{t}|{first_last}" if first_last else t


def _paper_keys(paper: dict[str, Any]) -> list[tuple[str, str]]:
    """回傳此 paper 可用的 dedup keys (按優先順序)"""
    keys: list[tuple[str, str]] = []
    doi = _extract_doi(paper)
    if doi:
        keys.append(("doi", doi))
    aid = _extract_arxiv_id(paper)
    if aid:
        keys.append(("arxiv", aid))
    fkey = _fuzzy_title_key(paper.get("title"), paper.get("authors"))
    if fkey:
        keys.append(("fuzzy", fkey))
    return keys


def _src_priority(paper: dict[str, Any]) -> int:
    src = paper.get("source")
    if isinstance(src, list):
        return min((SOURCE_PRIORITY.get(s, 99) for s in src), default=99)
    return SOURCE_PRIORITY.get(src or "arxiv", 99)


def _merge_into(primary: dict[str, Any], dup: dict[str, Any]) -> None:
    """把 dup 的資訊合併進 primary (in-place)。primary 是優先來源。"""
    # source 變 list
    p_src = primary.get("source")
    if not isinstance(p_src, list):
        p_src = [p_src] if p_src else []
    d_src = dup.get("source")
    if isinstance(d_src, list):
        for s in d_src:
            if s and s not in p_src:
                p_src.append(s)
    elif d_src and d_src not in p_src:
        p_src.append(d_src)
    primary["source"] = p_src

    # external_ids 合併
    p_ext = dict(primary.get("external_ids") or {})
    for k, v in (dup.get("external_ids") or {}).items():
        if v and not p_ext.get(k):
            p_ext[k] = v
    if p_ext:
        primary["external_ids"] = p_ext

    # citation count 取 max
    p_cit = primary.get("citation_count") or 0
    d_cit = dup.get("citation_count") or 0
    if d_cit > p_cit:
        primary["citation_count"] = d_cit

    # hf_upvotes 取 max (通常只 arXiv-side 有)
    p_hf = primary.get("hf_upvotes") or 0
    d_hf = dup.get("hf_upvotes") or 0
    if d_hf > p_hf:
        primary["hf_upvotes"] = d_hf

    # 缺欄位才補
    for field in ("summary", "venue", "published"):
        if not primary.get(field) and dup.get(field):
            primary[field] = dup[field]


def merge_sources(*lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把多個來源的 papers 合併去重。

    回傳順序:照 sources 進來的順序 (主來源在前的優先保留 metadata)。
    """
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    primaries: list[dict[str, Any]] = []  # 保持插入序

    for src_list in lists:
        for p in src_list:
            keys = _paper_keys(p)
            if not keys:
                primaries.append(p)
                continue
            # 找到任何一個 key 已存在 → 是 duplicate
            existing = None
            for k in keys:
                if k in by_key:
                    existing = by_key[k]
                    break
            if existing is None:
                # 新論文,所有 keys 指向它
                for k in keys:
                    by_key[k] = p
                primaries.append(p)
            else:
                # 合併到較優先的那一筆
                if _src_priority(p) < _src_priority(existing):
                    # 新來的更優先 → 用新來的當 primary, 把舊的合進去
                    _merge_into(p, existing)
                    # primaries list 替換
                    try:
                        idx = primaries.index(existing)
                        primaries[idx] = p
                    except ValueError:
                        primaries.append(p)
                    for k in _paper_keys(existing) + keys:
                        by_key[k] = p
                else:
                    _merge_into(existing, p)
                    for k in keys:
                        by_key.setdefault(k, existing)

    return primaries
