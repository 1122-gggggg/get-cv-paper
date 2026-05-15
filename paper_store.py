"""SQLite-backed persistent paper store.

L2 cache for /api/papers: rolling window of recently-fetched papers, keyed by
normalized paper id + primary_cat. Survives container restarts; falls back when
upstream sources are rate-limited or unreachable.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _paper_id(p: dict[str, Any]) -> str:
    ext = p.get("external_ids") or {}
    if ext.get("arxiv"):
        return f"arxiv:{ext['arxiv']}"
    if ext.get("doi"):
        return f"doi:{str(ext['doi']).lower().lstrip('/')}"
    url = p.get("url") or ""
    if url:
        return f"url:{url[:200]}"
    title = (p.get("title") or "").strip().lower()
    if title:
        return "title:" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:16]
    return "anon:" + hashlib.sha1(json.dumps(p, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _norm_published(p: dict[str, Any]) -> str:
    v = p.get("published") or ""
    if not v:
        return ""
    return str(v)[:10]


class PaperStore:
    """Thread-safe SQLite store for fetched papers.

    Composite key (paper_id, primary_cat) lets the same paper appear under
    multiple disciplines (cs.LG paper served to both ml and cv).
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()
        logger.info("paper_store: DB at %s", db_path)

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS papers (
                paper_id TEXT NOT NULL,
                primary_cat TEXT NOT NULL,
                published TEXT,
                payload BLOB NOT NULL,
                fetched_at REAL NOT NULL,
                PRIMARY KEY (paper_id, primary_cat)
            );
            CREATE INDEX IF NOT EXISTS idx_cat_pub ON papers(primary_cat, published DESC);
            CREATE INDEX IF NOT EXISTS idx_pub ON papers(published);
            CREATE TABLE IF NOT EXISTS meta (
                primary_cat TEXT PRIMARY KEY,
                last_fetched REAL NOT NULL,
                row_count INTEGER NOT NULL DEFAULT 0
            );
            """
        )

    def upsert_many(self, papers: list[dict[str, Any]], primary_cat: str) -> int:
        if not papers or not primary_cat:
            return 0
        now = time.time()
        rows: list[tuple[str, str, str, bytes, float]] = []
        for p in papers:
            pid = _paper_id(p)
            payload = json.dumps(p, ensure_ascii=False, default=str).encode("utf-8")
            rows.append((pid, primary_cat, _norm_published(p), payload, now))
        try:
            with self._lock:
                self._conn.execute("BEGIN")
                self._conn.executemany(
                    "INSERT OR REPLACE INTO papers(paper_id, primary_cat, published, payload, fetched_at) "
                    "VALUES(?,?,?,?,?)",
                    rows,
                )
                self._conn.execute(
                    "INSERT INTO meta(primary_cat, last_fetched, row_count) VALUES(?,?,?) "
                    "ON CONFLICT(primary_cat) DO UPDATE SET last_fetched=excluded.last_fetched, "
                    "row_count=(SELECT COUNT(*) FROM papers WHERE primary_cat=?)",
                    (primary_cat, now, len(rows), primary_cat),
                )
                self._conn.execute("COMMIT")
            return len(rows)
        except Exception as e:
            try:
                self._conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning("paper_store: upsert failed for %s: %s", primary_cat, e)
            return 0

    def _cutoff(self, days: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    def query(self, primary_cat: str, days: int, limit: int = 500) -> list[dict[str, Any]]:
        if not primary_cat:
            return []
        cutoff = self._cutoff(days)
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT payload FROM papers WHERE primary_cat=? AND published>=? "
                    "ORDER BY published DESC LIMIT ?",
                    (primary_cat, cutoff, limit),
                )
                rows = cur.fetchall()
            return [json.loads(r[0]) for r in rows]
        except Exception as e:
            logger.warning("paper_store: query failed for %s: %s", primary_cat, e)
            return []

    def query_multi(self, primary_cats: list[str], days: int, limit: int = 500) -> list[dict[str, Any]]:
        if not primary_cats:
            return []
        cutoff = self._cutoff(days)
        placeholders = ",".join("?" for _ in primary_cats)
        try:
            with self._lock:
                cur = self._conn.execute(
                    f"SELECT payload FROM papers WHERE primary_cat IN ({placeholders}) "
                    f"AND published>=? ORDER BY published DESC LIMIT ?",
                    (*primary_cats, cutoff, limit),
                )
                rows = cur.fetchall()
            out: list[dict[str, Any]] = []
            seen: set[str] = set()
            for r in rows:
                p = json.loads(r[0])
                pid = _paper_id(p)
                if pid not in seen:
                    seen.add(pid)
                    out.append(p)
            return out
        except Exception as e:
            logger.warning("paper_store: query_multi failed: %s", e)
            return []

    def last_fetched(self, primary_cat: str) -> float | None:
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT last_fetched FROM meta WHERE primary_cat=?", (primary_cat,)
                ).fetchone()
            return float(row[0]) if row else None
        except Exception:
            return None

    def cleanup(self, max_age_days: int = 100) -> int:
        cutoff = self._cutoff(max_age_days)
        try:
            with self._lock:
                cur = self._conn.execute("DELETE FROM papers WHERE published<?", (cutoff,))
                deleted = cur.rowcount or 0
            if deleted:
                logger.info("paper_store: pruned %d rows older than %s", deleted, cutoff)
            return deleted
        except Exception as e:
            logger.warning("paper_store: cleanup failed: %s", e)
            return 0

    def stats(self) -> dict[str, Any]:
        try:
            with self._lock:
                total = int(self._conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0])
                by_cat = self._conn.execute(
                    "SELECT primary_cat, COUNT(*) FROM papers GROUP BY primary_cat ORDER BY 2 DESC"
                ).fetchall()
                disk = self.db_path.stat().st_size if self.db_path.exists() else 0
            return {
                "total": total,
                "disk_bytes": disk,
                "by_cat": {c: int(n) for c, n in by_cat},
            }
        except Exception:
            return {"total": 0, "disk_bytes": 0, "by_cat": {}}

    def close(self) -> None:
        try:
            with self._lock:
                self._conn.close()
        except Exception:
            pass
