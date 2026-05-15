"""Query → paper semantic ranking via Hugging Face Inference embeddings.

Embeddings are computed on demand and held in a memory LRU keyed by stable
paper id (no DB). HF token comes from env (HF_TOKEN); model from HF_EMBED_MODEL
(default: multilingual e5-small). All calls go through the shared httpx client.
"""
from __future__ import annotations

import logging
import math
import os
from collections import OrderedDict
from typing import Any

import httpx

logger = logging.getLogger(__name__)

HF_TOKEN = (os.environ.get("HF_TOKEN") or "").strip()
HF_EMBED_MODEL = (os.environ.get("HF_EMBED_MODEL") or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2").strip()
_HF_LEGACY = "https://api-inference.huggingface.co/models"
_HF_ROUTER = "https://router.huggingface.co/hf-inference/models"
_BATCH_SIZE = 16
_HTTP_TIMEOUT = 45.0


class _EmbedCache:
    def __init__(self, maxsize: int = 5000) -> None:
        self._d: "OrderedDict[str, list[float]]" = OrderedDict()
        self._max = maxsize

    def get(self, key: str) -> list[float] | None:
        v = self._d.get(key)
        if v is not None:
            self._d.move_to_end(key)
        return v

    def put(self, key: str, vec: list[float]) -> None:
        self._d[key] = vec
        self._d.move_to_end(key)
        while len(self._d) > self._max:
            self._d.popitem(last=False)

    def __len__(self) -> int:
        return len(self._d)


_cache = _EmbedCache()


def _paper_key(paper: dict[str, Any]) -> str:
    return (
        paper.get("id")
        or paper.get("doi")
        or paper.get("link")
        or paper.get("url")
        or paper.get("title")
        or ""
    )


def _passage_text(paper: dict[str, Any]) -> str:
    title = (paper.get("title") or "").strip()
    body = (paper.get("summary") or paper.get("abstract") or "").strip()
    body = body[:600]
    prefix = "passage: "
    if title and body:
        return f"{prefix}{title}\n{body}"
    return f"{prefix}{title or body}"


def _query_text(q: str) -> str:
    return f"query: {q.strip()}"


def _mean_pool(token_vecs: list[list[float]]) -> list[float]:
    if not token_vecs:
        return []
    return [sum(col) / len(col) for col in zip(*token_vecs)]


def _flatten_vec(v: Any) -> list[float] | None:
    """HF feature-extraction may return [vec] (sentence-level) or [[vec_i, ...]] (token-level)."""
    if not isinstance(v, list) or not v:
        return None
    if isinstance(v[0], (int, float)):
        return [float(x) for x in v]
    if isinstance(v[0], list):
        return _mean_pool(v)
    return None


async def _hf_post(client: httpx.AsyncClient, url: str, payload: dict) -> httpx.Response:
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    return await client.post(url, headers=headers, json=payload, timeout=_HTTP_TIMEOUT)


async def _hf_embed(client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
    if not HF_TOKEN:
        raise RuntimeError("HF_TOKEN not configured")
    payload = {"inputs": texts, "options": {"wait_for_model": True}}
    legacy_url = f"{_HF_LEGACY}/{HF_EMBED_MODEL}"
    r = await _hf_post(client, legacy_url, payload)
    if r.status_code in (401, 403, 404):
        router_url = f"{_HF_ROUTER}/{HF_EMBED_MODEL}/pipeline/feature-extraction"
        r = await _hf_post(client, router_url, payload)
    if r.status_code != 200:
        raise RuntimeError(f"HF embed {r.status_code}: {r.text[:200]}")
    data = r.json()
    out: list[list[float]] = []
    for v in data:
        flat = _flatten_vec(v)
        if flat is None:
            raise RuntimeError("HF embed: unexpected response shape")
        out.append(flat)
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    s = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        s += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return s / (math.sqrt(na) * math.sqrt(nb))


async def _embed_papers(
    client: httpx.AsyncClient, papers: list[dict[str, Any]]
) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    pending: list[tuple[str, str]] = []
    for p in papers:
        k = _paper_key(p)
        if not k:
            continue
        cached = _cache.get(k)
        if cached is not None:
            out[k] = cached
        else:
            pending.append((k, _passage_text(p)))

    for i in range(0, len(pending), _BATCH_SIZE):
        chunk = pending[i : i + _BATCH_SIZE]
        keys = [k for k, _ in chunk]
        texts = [t for _, t in chunk]
        try:
            vecs = await _hf_embed(client, texts)
        except Exception as e:
            logger.warning("semantic: embed batch failed: %s", e)
            continue
        if len(vecs) != len(chunk):
            logger.warning("semantic: shape mismatch (%d != %d)", len(vecs), len(chunk))
            continue
        for k, v in zip(keys, vecs):
            _cache.put(k, v)
            out[k] = v
    return out


async def semantic_rank(
    client: httpx.AsyncClient,
    query: str,
    papers: list[dict[str, Any]],
    top_k: int = 30,
) -> list[dict[str, Any]]:
    """Return papers sorted by cosine sim to query, top_k slice with `semantic_score`."""
    query = (query or "").strip()
    if not query or not papers:
        return []

    q_vecs = await _hf_embed(client, [_query_text(query)])
    if not q_vecs:
        return []
    q_vec = q_vecs[0]

    paper_vecs = await _embed_papers(client, papers)

    scored: list[tuple[float, dict[str, Any]]] = []
    for p in papers:
        v = paper_vecs.get(_paper_key(p))
        if not v:
            continue
        scored.append((_cosine(q_vec, v), p))
    scored.sort(key=lambda x: x[0], reverse=True)

    out: list[dict[str, Any]] = []
    for s, p in scored[:top_k]:
        item = dict(p)
        item["semantic_score"] = round(s, 4)
        out.append(item)
    return out


def cache_stats() -> dict[str, int]:
    return {"size": len(_cache), "max": _cache._max}
