"""Query → paper semantic ranking via Hugging Face Inference embeddings.

Embeddings are computed on demand and held in a memory LRU keyed by stable
paper id, backed by an L2 SQLite cache. HF token comes from env (HF_TOKEN);
model from HF_EMBED_MODEL (default: paraphrase-multilingual-MiniLM-L12-v2).
e5-family models get "query:"/"passage:" prefixes; others are sent raw.
All calls go through the shared httpx client.
"""
from __future__ import annotations

import logging
import math
import os
import random as _random
import re as _re_cluster
import sqlite3
import struct
import threading
import time
from collections import Counter as _Counter, OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

HF_TOKEN = (os.environ.get("HF_TOKEN") or "").strip()
HF_EMBED_MODEL = (os.environ.get("HF_EMBED_MODEL") or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2").strip()
# e5/gte/bge-style models need instruction prefixes; generic ST models do not.
_IS_E5 = any(t in HF_EMBED_MODEL.lower() for t in ("e5", "gte", "bge"))
# Bump when the embedding text/prefix scheme changes so stale vectors are bypassed.
_EMBED_VERSION = "v2"
_EMBED_CACHE_MODEL = f"{HF_EMBED_MODEL}#{_EMBED_VERSION}"
_HF_LEGACY = "https://api-inference.huggingface.co/models"
_HF_ROUTER = "https://router.huggingface.co/hf-inference/models"
_BATCH_SIZE = 16
_HTTP_TIMEOUT = 45.0
_DB_MAX_ROWS = 20000
_PRUNE_EVERY = 1000


def _resolve_db_path() -> Path | None:
    candidates = [
        os.environ.get("EMBED_CACHE_PATH"),
        (os.environ.get("CACHE_DIR") or "") + "/embed.sqlite" if os.environ.get("CACHE_DIR") else None,
        ".cache/embed.sqlite",
    ]
    for c in candidates:
        if not c:
            continue
        try:
            p = Path(c)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "ab"):
                pass
            return p
        except Exception:
            continue
    return None


class _EmbedCache:
    def __init__(self, maxsize: int = 5000) -> None:
        self._mem: "OrderedDict[str, list[float]]" = OrderedDict()
        self._max = maxsize
        self._lock = threading.Lock()
        self._put_count = 0
        self._db_path = _resolve_db_path()
        self._conn: sqlite3.Connection | None = None
        if self._db_path is not None:
            try:
                self._conn = sqlite3.connect(
                    str(self._db_path), check_same_thread=False, isolation_level=None
                )
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=NORMAL")
                self._conn.execute(
                    "CREATE TABLE IF NOT EXISTS embeddings ("
                    " key TEXT NOT NULL,"
                    " model TEXT NOT NULL,"
                    " vec BLOB NOT NULL,"
                    " at REAL NOT NULL,"
                    " PRIMARY KEY (key, model))"
                )
                logger.info("semantic: embed cache DB at %s", self._db_path)
            except Exception as e:
                logger.warning("semantic: SQLite init failed (%s), L1-only", e)
                self._conn = None

    @staticmethod
    def _encode(vec: list[float]) -> bytes:
        return struct.pack(f"<{len(vec)}f", *vec)

    @staticmethod
    def _decode(blob: bytes) -> list[float]:
        n = len(blob) // 4
        return list(struct.unpack(f"<{n}f", blob))

    def get(self, key: str) -> list[float] | None:
        v = self._mem.get(key)
        if v is not None:
            self._mem.move_to_end(key)
            return v
        if self._conn is None:
            return None
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT vec FROM embeddings WHERE key=? AND model=?",
                    (key, _EMBED_CACHE_MODEL),
                ).fetchone()
            if row is None:
                return None
            vec = self._decode(row[0])
            self._mem[key] = vec
            self._mem.move_to_end(key)
            while len(self._mem) > self._max:
                self._mem.popitem(last=False)
            return vec
        except Exception as e:
            logger.debug("semantic: SQLite get failed: %s", e)
            return None

    def put(self, key: str, vec: list[float]) -> None:
        self._mem[key] = vec
        self._mem.move_to_end(key)
        while len(self._mem) > self._max:
            self._mem.popitem(last=False)
        if self._conn is None:
            return
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO embeddings(key, model, vec, at) VALUES(?,?,?,?)",
                    (key, _EMBED_CACHE_MODEL, self._encode(vec), time.time()),
                )
                self._put_count += 1
                due = self._put_count % _PRUNE_EVERY == 0
        except Exception as e:
            logger.debug("semantic: SQLite put failed: %s", e)
            return
        if due:
            self.prune()

    def prune(self) -> None:
        if self._conn is None:
            return
        try:
            with self._lock:
                cnt = self._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
                if cnt > _DB_MAX_ROWS:
                    self._conn.execute(
                        "DELETE FROM embeddings WHERE rowid IN ("
                        " SELECT rowid FROM embeddings ORDER BY at ASC LIMIT ?)",
                        (cnt - _DB_MAX_ROWS,),
                    )
        except Exception:
            pass

    def __len__(self) -> int:
        return len(self._mem)

    def disk_size(self) -> int:
        if self._conn is None:
            return 0
        try:
            with self._lock:
                return int(self._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0])
        except Exception:
            return 0


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
    prefix = "passage: " if _IS_E5 else ""
    if title and body:
        return f"{prefix}{title}\n{body}"
    return f"{prefix}{title or body}"


def _query_text(q: str) -> str:
    q = q.strip()
    return f"query: {q}" if _IS_E5 else q


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
    return {"size": len(_cache), "max": _cache._max, "disk": _cache.disk_size()}


async def rerank_by_centroid(
    client: httpx.AsyncClient,
    favorite_papers: list[dict[str, Any]],
    candidate_papers: list[dict[str, Any]],
    top_k: int = 30,
    blend: float = 0.4,
) -> list[dict[str, Any]]:
    """以使用者收藏的論文 embedding 取質心,對 candidates 重新排序。

    `blend` 控制原始順序 vs 個人化分數的權重:0=純個人化,1=純原始。
    回傳前 top_k 個 candidates,每篇附 `personal_score` (0..1)。
    """
    if not favorite_papers or not candidate_papers:
        return candidate_papers[:top_k]

    fav_vecs_map = await _embed_papers(client, favorite_papers)
    fav_vecs = [v for v in fav_vecs_map.values() if v]
    if not fav_vecs:
        return candidate_papers[:top_k]

    # 多質心:把收藏分群成 1-3 個興趣中心,候選取「最相近的興趣」分數,
    # 避免把多元興趣平均成一個模糊質心。
    centroids = _multi_centroids(fav_vecs)
    if not centroids:
        return candidate_papers[:top_k]

    # 冷啟動:收藏太少(<3)時質心噪音大,提高 blend 偏向原始排序避免過擬合。
    eff_blend = blend
    if len(fav_vecs) < 3:
        eff_blend = min(1.0, blend + 0.25)

    cand_vecs_map = await _embed_papers(client, candidate_papers)

    scored: list[tuple[float, int, dict[str, Any]]] = []
    fav_keys = set(fav_vecs_map.keys())
    n_cand = len(candidate_papers)
    for idx, p in enumerate(candidate_papers):
        k = _paper_key(p)
        if not k or k in fav_keys:
            # 跳過已收藏的(不要把收藏放回推薦列表)
            continue
        v = cand_vecs_map.get(k)
        if not v:
            scored.append((0.0, idx, p))
            continue
        sim = max(_cosine(c, v) for c in centroids)  # -1..1,取最相近興趣
        personal = (sim + 1.0) / 2.0  # 0..1
        # 原始排名也歸一化(idx 越小越前)
        pos_score = 1.0 - (idx / max(1, n_cand))
        score = eff_blend * pos_score + (1.0 - eff_blend) * personal
        scored.append((score, idx, p))

    scored.sort(key=lambda x: (-x[0], x[1]))

    out: list[dict[str, Any]] = []
    for s, _idx, p in scored[:top_k]:
        item = dict(p)
        item["personal_score"] = round(s, 4)
        out.append(item)
    return out


# ── 動態子題聚類 (k-means on cached embeddings) ────────────────
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with", "by", "from",
    "is", "are", "be", "as", "at", "this", "that", "we", "our", "their", "its",
    "using", "based", "via", "novel", "new", "method", "approach", "model", "models",
    "framework", "task", "tasks", "study", "studies", "paper", "results", "result",
    "show", "shows", "propose", "proposed", "show", "however", "while", "but",
    "can", "may", "have", "has", "such", "across", "each", "more", "than", "also",
    "first", "second", "well", "many", "most", "use", "used", "uses", "given",
    "data", "training", "performance", "quality", "high", "low", "large", "small",
    "learning", "deep", "neural", "network", "networks",  # too generic
})
_TOK_RE = _re_cluster.compile(r"[a-zA-Z][a-zA-Z\-]{2,}")


def _tokenize_title(t: str) -> list[str]:
    return [w.lower() for w in _TOK_RE.findall(t or "") if w.lower() not in _STOPWORDS and len(w) >= 4]


def _kmeans_pp_seed(vecs: list[list[float]], k: int) -> list[list[float]]:
    """k-means++ 初始化(避免隨機 seed 落入退化解)。"""
    if not vecs or k <= 0:
        return []
    if len(vecs) <= k:
        return [list(v) for v in vecs]
    centroids: list[list[float]] = [list(_random.choice(vecs))]
    for _ in range(k - 1):
        dists = []
        for v in vecs:
            d = min(1.0 - _cosine(v, c) for c in centroids)
            dists.append(max(0.0, d))
        total = sum(dists) or 1e-9
        # weighted random pick
        r = _random.random() * total
        acc = 0.0
        pick = vecs[-1]
        for v, d in zip(vecs, dists):
            acc += d
            if acc >= r:
                pick = v
                break
        centroids.append(list(pick))
    return centroids


def _kmeans(vecs: list[list[float]], k: int, max_iter: int = 12) -> tuple[list[int], list[list[float]]]:
    """純 Python mini k-means (cosine similarity)。回傳 (assign, centroids)。"""
    n = len(vecs)
    if n == 0 or k <= 0:
        return [], []
    k = min(k, n)
    centroids = _kmeans_pp_seed(vecs, k)
    assign = [0] * n
    dim = len(vecs[0])
    for _ in range(max_iter):
        # Assign
        changed = 0
        for i, v in enumerate(vecs):
            best, best_sim = 0, -2.0
            for ci, c in enumerate(centroids):
                s = _cosine(v, c)
                if s > best_sim:
                    best_sim, best = s, ci
            if assign[i] != best:
                changed += 1
                assign[i] = best
        if changed == 0:
            break
        # Update centroids (mean)
        new_cents = [[0.0] * dim for _ in range(k)]
        counts = [0] * k
        for i, v in enumerate(vecs):
            c = assign[i]
            counts[c] += 1
            for d in range(dim):
                new_cents[c][d] += v[d]
        for c in range(k):
            if counts[c] > 0:
                for d in range(dim):
                    new_cents[c][d] /= counts[c]
            else:
                # 空 cluster 給 random vec 重啟,避免維度全 0
                new_cents[c] = list(_random.choice(vecs))
        centroids = new_cents
    return assign, centroids


def _normalize_vec(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _mean_centroid(vecs: list[list[float]]) -> list[float]:
    dim = len(vecs[0])
    acc = [0.0] * dim
    for v in vecs:
        if len(v) != dim:
            continue
        for i in range(dim):
            acc[i] += v[i]
    n = len(vecs)
    return _normalize_vec([x / n for x in acc])


def _multi_centroids(fav_vecs: list[list[float]], max_k: int = 3) -> list[list[float]]:
    """把收藏分群成最多 max_k 個興趣質心(支援多元興趣使用者)。

    收藏很少 → 單一均值質心;否則 k-means(k≈n/2,上限 max_k)。
    """
    if not fav_vecs:
        return []
    n = len(fav_vecs)
    if n <= 2:
        return [_mean_centroid(fav_vecs)]
    k = max(1, min(max_k, n // 2))
    if k == 1:
        return [_mean_centroid(fav_vecs)]
    _assign, cents = _kmeans(fav_vecs, k)
    out = [_normalize_vec(c) for c in cents if any(c)]
    return out or [_mean_centroid(fav_vecs)]


def _cluster_label(papers: list[dict[str, Any]]) -> str:
    """從一群論文標題中抓最常見的 1-2 字 phrase 當 cluster 標籤。"""
    if not papers:
        return "misc"
    tokens: list[str] = []
    bigrams: list[str] = []
    for p in papers:
        ts = _tokenize_title(p.get("title") or "")
        tokens.extend(ts)
        for i in range(len(ts) - 1):
            bigrams.append(f"{ts[i]} {ts[i+1]}")
    if not tokens:
        return "misc"
    bg_top = _Counter(bigrams).most_common(1)
    if bg_top and bg_top[0][1] >= max(2, len(papers) // 4):
        return bg_top[0][0]
    tk_top = _Counter(tokens).most_common(1)
    return tk_top[0][0] if tk_top else "misc"


async def cluster_papers(
    client: httpx.AsyncClient,
    papers: list[dict[str, Any]],
    k: int = 6,
    min_cluster: int = 3,
) -> list[dict[str, Any]]:
    """對一組論文做 k-means 聚類,回傳 [{label, count, sample_titles}].

    只用既有 cache 過的 embedding(若該批論文已被 warmup 過,即不打 HF API)。
    沒 embedding 的論文會略過。
    """
    if not papers:
        return []
    keyed: list[tuple[str, dict[str, Any]]] = []
    for p in papers:
        k_ = _paper_key(p)
        if k_:
            keyed.append((k_, p))
    if not keyed:
        return []
    paper_vecs = await _embed_papers(client, [p for _, p in keyed])

    vecs: list[list[float]] = []
    papers_aligned: list[dict[str, Any]] = []
    for k_, p in keyed:
        v = paper_vecs.get(k_)
        if v:
            vecs.append(v)
            papers_aligned.append(p)
    if len(vecs) < min_cluster:
        return []

    k_eff = max(2, min(k, len(vecs) // min_cluster))
    assign, _ = _kmeans(vecs, k_eff)

    buckets: dict[int, list[dict[str, Any]]] = {}
    for i, p in enumerate(papers_aligned):
        buckets.setdefault(assign[i], []).append(p)

    out: list[dict[str, Any]] = []
    for cid, members in buckets.items():
        if len(members) < min_cluster:
            continue
        label = _cluster_label(members)
        out.append({
            "label": label,
            "count": len(members),
            "momentum": _recent_share(members),
            "sample_titles": [m.get("title", "")[:120] for m in members[:5]],
        })
    out.sort(key=lambda x: x["count"], reverse=True)
    return out


def _recent_share(members: list[dict[str, Any]], days: int = 3) -> float:
    """Fraction of a cluster published within the last `days` — a cheap heat proxy.

    A subtopic dominated by brand-new papers is warming up; ISO date-prefix string
    comparison avoids per-paper datetime parsing.
    """
    if not members:
        return 0.0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    recent = sum(1 for m in members if str(m.get("published") or "")[:10] >= cutoff)
    return round(recent / len(members), 3)


# ── BM25 lexical scoring + Reciprocal Rank Fusion (hybrid recall) ──────
_BM25_TOK_RE = _re_cluster.compile(r"[a-zA-Z0-9][a-zA-Z0-9\-]+")
_RRF_K = 60


def _bm25_tokens(text: str) -> list[str]:
    return [w.lower() for w in _BM25_TOK_RE.findall(text or "")]


def _bm25_doc_text(paper: dict[str, Any]) -> str:
    title = (paper.get("title") or "").strip()
    body = (paper.get("summary") or paper.get("abstract") or "").strip()[:600]
    return f"{title} {body}"


def _bm25_scores(
    query: str, papers: list[dict[str, Any]], k1: float = 1.5, b: float = 0.75
) -> dict[int, float]:
    """Okapi BM25 over the in-memory pool. Pure Python, no network. {idx: score}."""
    q_terms = set(_bm25_tokens(query))
    if not q_terms or not papers:
        return {}
    docs = [_bm25_tokens(_bm25_doc_text(p)) for p in papers]
    n_docs = len(docs)
    avgdl = sum(len(d) for d in docs) / max(1, n_docs)
    doc_tfs: list[dict[str, int]] = []
    df: dict[str, int] = {}
    for d in docs:
        tf = _Counter(d)
        doc_tfs.append(tf)
        for term in tf:
            df[term] = df.get(term, 0) + 1
    scores: dict[int, float] = {}
    for i, tf in enumerate(doc_tfs):
        dl = len(docs[i]) or 1
        s = 0.0
        for term in q_terms:
            f = tf.get(term, 0)
            if not f:
                continue
            n_q = df.get(term, 0)
            idf = math.log(1 + (n_docs - n_q + 0.5) / (n_q + 0.5))
            s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        if s > 0:
            scores[i] = s
    return scores


def _ranks_from_scores(scores: dict[int, float]) -> dict[int, int]:
    """Map idx → 1-based rank by descending score (ties broken by idx)."""
    order = sorted(scores, key=lambda i: (-scores[i], i))
    return {idx: rank for rank, idx in enumerate(order, start=1)}


async def _dense_scores(
    client: httpx.AsyncClient, query: str, papers: list[dict[str, Any]]
) -> dict[int, float]:
    q_vecs = await _hf_embed(client, [_query_text(query)])
    if not q_vecs:
        raise RuntimeError("empty query embedding")
    q_vec = q_vecs[0]
    paper_vecs = await _embed_papers(client, papers)
    scores: dict[int, float] = {}
    for i, p in enumerate(papers):
        v = paper_vecs.get(_paper_key(p))
        if v:
            scores[i] = _cosine(q_vec, v)
    return scores


async def hybrid_rank(
    client: httpx.AsyncClient,
    query: str,
    papers: list[dict[str, Any]],
    top_k: int = 30,
    rrf_k: int = _RRF_K,
) -> dict[str, Any]:
    """BM25 ⊕ dense via Reciprocal Rank Fusion.

    Dense 是 best-effort:HF embedding 失敗時退化成 BM25-only 而非拋錯,
    讓召回端在 embedding 服務中斷時也不會 502。
    回傳 {papers, dense, lexical},每篇附 hybrid/semantic/lexical 分數。
    """
    query = (query or "").strip()
    if not query or not papers:
        return {"papers": [], "dense": False, "lexical": False}

    bm25 = _bm25_scores(query, papers)
    bm25_ranks = _ranks_from_scores(bm25)

    dense_scores: dict[int, float] = {}
    dense_ranks: dict[int, int] = {}
    dense_ok = False
    try:
        dense_scores = await _dense_scores(client, query, papers)
        dense_ranks = _ranks_from_scores(dense_scores)
        dense_ok = True
    except Exception as e:
        logger.warning("hybrid_rank: dense stage failed, BM25-only fallback: %s", e)

    idxs = set(bm25_ranks) | set(dense_ranks)
    if not idxs:
        return {"papers": [], "dense": dense_ok, "lexical": bool(bm25)}

    fused: dict[int, float] = {}
    for i in idxs:
        s = 0.0
        r_b = bm25_ranks.get(i)
        if r_b is not None:
            s += 1.0 / (rrf_k + r_b)
        r_d = dense_ranks.get(i)
        if r_d is not None:
            s += 1.0 / (rrf_k + r_d)
        fused[i] = s

    order = sorted(idxs, key=lambda i: (fused[i], dense_scores.get(i, 0.0)), reverse=True)
    out: list[dict[str, Any]] = []
    for i in order[:top_k]:
        item = dict(papers[i])
        item["hybrid_score"] = round(fused[i], 6)
        if i in dense_scores:
            item["semantic_score"] = round(dense_scores[i], 4)
        if i in bm25:
            item["lexical_score"] = round(bm25[i], 4)
        out.append(item)
    return {"papers": out, "dense": dense_ok, "lexical": bool(bm25)}
