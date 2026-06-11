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
        self._migrate()
        logger.info("paper_store: DB at %s", db_path)

    def _migrate(self) -> None:
        """加新欄位給既有 DB(CREATE TABLE IF NOT EXISTS 不會 ALTER 舊表)。"""
        try:
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(metric_snapshots)")}
            if "github_stars" not in cols:
                self._conn.execute("ALTER TABLE metric_snapshots ADD COLUMN github_stars INTEGER")
                logger.info("paper_store: migrated metric_snapshots +github_stars")
        except Exception as e:
            logger.warning("paper_store: migration failed: %s", e)

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
            CREATE TABLE IF NOT EXISTS metric_snapshots (
                paper_id TEXT NOT NULL,
                primary_cat TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                citation_count INTEGER,
                hf_upvotes INTEGER,
                github_stars INTEGER,
                published TEXT,
                at REAL NOT NULL,
                PRIMARY KEY (paper_id, primary_cat, snapshot_date)
            );
            CREATE INDEX IF NOT EXISTS idx_snap_cat_date ON metric_snapshots(primary_cat, snapshot_date);
            CREATE TABLE IF NOT EXISTS topic_daily (
                primary_cat TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                paper_count INTEGER NOT NULL,
                fresh_count INTEGER NOT NULL,
                at REAL NOT NULL,
                PRIMARY KEY (primary_cat, snapshot_date)
            );
            CREATE TABLE IF NOT EXISTS paper_views (
                paper_id TEXT NOT NULL,
                view_date TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                url TEXT,
                title TEXT,
                last_at REAL NOT NULL,
                PRIMARY KEY (paper_id, view_date)
            );
            CREATE INDEX IF NOT EXISTS idx_views_date ON paper_views(view_date);
            CREATE TABLE IF NOT EXISTS oai_state (
                oai_set TEXT PRIMARY KEY,
                last_date TEXT NOT NULL,
                last_at REAL NOT NULL
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

    # ── time-series: daily metric snapshots + topic volume ──────────
    def record_snapshots(self, papers: list[dict[str, Any]], primary_cat: str) -> int:
        """Capture today's citation/hf reading per paper (idempotent per UTC day).

        Same-day re-builds converge to the day's MAX observed value, so a later
        build that carries fresh S2 citations upgrades an earlier zero/None.
        Also records one topic_daily volume row per category per day.
        """
        if not papers or not primary_cat:
            return 0
        now = time.time()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        fresh_cutoff = self._cutoff(2)
        snap_rows: list[tuple[str, str, str, int | None, int | None, int | None, str, float]] = []
        fresh = 0
        for p in papers:
            pid = _paper_id(p)
            cit = p.get("citation_count")
            hf = p.get("hf_upvotes")
            stars = p.get("github_stars")
            cit_i = int(cit) if isinstance(cit, (int, float)) and cit >= 0 else None
            hf_i = int(hf) if isinstance(hf, (int, float)) and hf >= 0 else None
            stars_i = int(stars) if isinstance(stars, (int, float)) and stars >= 0 else None
            pub = _norm_published(p)
            if pub and pub >= fresh_cutoff:
                fresh += 1
            snap_rows.append((pid, primary_cat, today, cit_i, hf_i, stars_i, pub, now))
        try:
            with self._lock:
                self._conn.execute("BEGIN")
                self._conn.executemany(
                    "INSERT INTO metric_snapshots"
                    "(paper_id, primary_cat, snapshot_date, citation_count, hf_upvotes, github_stars, published, at) "
                    "VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(paper_id, primary_cat, snapshot_date) DO UPDATE SET "
                    " citation_count=MAX(COALESCE(citation_count,0), COALESCE(excluded.citation_count,0)), "
                    " hf_upvotes=MAX(COALESCE(hf_upvotes,0), COALESCE(excluded.hf_upvotes,0)), "
                    " github_stars=MAX(COALESCE(github_stars,0), COALESCE(excluded.github_stars,0)), "
                    " at=excluded.at",
                    snap_rows,
                )
                self._conn.execute(
                    "INSERT INTO topic_daily(primary_cat, snapshot_date, paper_count, fresh_count, at) "
                    "VALUES(?,?,?,?,?) "
                    "ON CONFLICT(primary_cat, snapshot_date) DO UPDATE SET "
                    " paper_count=MAX(paper_count, excluded.paper_count), "
                    " fresh_count=MAX(fresh_count, excluded.fresh_count), "
                    " at=excluded.at",
                    (primary_cat, today, len(snap_rows), fresh, now),
                )
                self._conn.execute("COMMIT")
            return len(snap_rows)
        except Exception as e:
            try:
                self._conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning("paper_store: record_snapshots failed for %s: %s", primary_cat, e)
            return 0

    def metric_deltas(self, primary_cat: str, window_days: int = 7, limit: int = 300) -> list[dict[str, Any]]:
        """Per-paper newest-vs-oldest snapshot within the window (for burst detection).

        Returns rows with at least two distinct snapshot dates so a delta is meaningful.
        """
        if not primary_cat:
            return []
        cutoff = self._cutoff(window_days)
        sql = (
            "WITH ranked AS ("
            "  SELECT paper_id, snapshot_date,"
            "         COALESCE(citation_count,0) AS cit, COALESCE(hf_upvotes,0) AS hf,"
            "         COALESCE(github_stars,0) AS gh,"
            "         ROW_NUMBER() OVER (PARTITION BY paper_id ORDER BY snapshot_date DESC) AS rn_new,"
            "         ROW_NUMBER() OVER (PARTITION BY paper_id ORDER BY snapshot_date ASC)  AS rn_old"
            "  FROM metric_snapshots WHERE primary_cat=? AND snapshot_date>=?"
            ") "
            "SELECT n.paper_id, n.cit, o.cit, n.hf, o.hf, n.gh, o.gh, n.snapshot_date, o.snapshot_date "
            "FROM ranked n JOIN ranked o USING(paper_id) "
            "WHERE n.rn_new=1 AND o.rn_old=1 AND n.snapshot_date<>o.snapshot_date "
            "LIMIT ?"
        )
        try:
            with self._lock:
                rows = self._conn.execute(sql, (primary_cat, cutoff, limit)).fetchall()
            return [
                {
                    "paper_id": r[0],
                    "cit_new": int(r[1]), "cit_old": int(r[2]),
                    "hf_new": int(r[3]), "hf_old": int(r[4]),
                    "star_new": int(r[5]), "star_old": int(r[6]),
                    "date_new": r[7], "date_old": r[8],
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("paper_store: metric_deltas failed for %s: %s", primary_cat, e)
            return []

    def topic_volume_series(self, primary_cat: str, days: int = 14) -> list[dict[str, Any]]:
        """Daily (paper_count, fresh_count) series for a category, oldest→newest."""
        if not primary_cat:
            return []
        cutoff = self._cutoff(days)
        try:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT snapshot_date, paper_count, fresh_count FROM topic_daily "
                    "WHERE primary_cat=? AND snapshot_date>=? ORDER BY snapshot_date ASC",
                    (primary_cat, cutoff),
                ).fetchall()
            return [{"date": r[0], "paper_count": int(r[1]), "fresh_count": int(r[2])} for r in rows]
        except Exception as e:
            logger.warning("paper_store: topic_volume_series failed for %s: %s", primary_cat, e)
            return []

    def payloads_by_ids(self, paper_ids: list[str], primary_cat: str) -> dict[str, dict[str, Any]]:
        """Fetch stored payloads for a set of paper_ids within one category."""
        if not paper_ids or not primary_cat:
            return {}
        out: dict[str, dict[str, Any]] = {}
        try:
            with self._lock:
                for i in range(0, len(paper_ids), 400):
                    chunk = paper_ids[i : i + 400]
                    ph = ",".join("?" for _ in chunk)
                    rows = self._conn.execute(
                        f"SELECT paper_id, payload FROM papers WHERE primary_cat=? AND paper_id IN ({ph})",
                        (primary_cat, *chunk),
                    ).fetchall()
                    for pid, payload in rows:
                        out[pid] = json.loads(payload)
        except Exception as e:
            logger.warning("paper_store: payloads_by_ids failed: %s", e)
        return out

    def github_urls_for_arxiv(self, arxiv_ids: list[str]) -> dict[str, str]:
        """{arxiv_id: github_url} — 跨 cat 查 payload 取 github_url(供 stars 解析)。"""
        if not arxiv_ids:
            return {}
        pids = [f"arxiv:{a}" for a in arxiv_ids]
        out: dict[str, str] = {}
        try:
            with self._lock:
                for i in range(0, len(pids), 400):
                    chunk = pids[i : i + 400]
                    ph = ",".join("?" for _ in chunk)
                    rows = self._conn.execute(
                        f"SELECT paper_id, payload FROM papers WHERE paper_id IN ({ph})",
                        tuple(chunk),
                    ).fetchall()
                    for pid, payload in rows:
                        aid = pid.split("arxiv:", 1)[-1]
                        if aid in out:
                            continue
                        gh = (json.loads(payload) or {}).get("github_url")
                        if gh:
                            out[aid] = gh
        except Exception as e:
            logger.warning("paper_store: github_urls_for_arxiv failed: %s", e)
        return out

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

    # ── OAI-PMH incremental harvest state: last datestamp per set ────
    def oai_get_state(self, oai_set: str) -> str | None:
        """Last successfully-harvested OAI datestamp (YYYY-MM-DD) for a set."""
        if not oai_set:
            return None
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT last_date FROM oai_state WHERE oai_set=?", (oai_set,)
                ).fetchone()
            return str(row[0]) if row else None
        except Exception:
            return None

    def oai_set_state(self, oai_set: str, last_date: str) -> None:
        if not oai_set or not last_date:
            return
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO oai_state(oai_set, last_date, last_at) VALUES(?,?,?) "
                    "ON CONFLICT(oai_set) DO UPDATE SET last_date=excluded.last_date, "
                    "last_at=excluded.last_at",
                    (oai_set, last_date, time.time()),
                )
        except Exception as e:
            logger.warning("paper_store: oai_set_state failed for %s: %s", oai_set, e)

    # ── view telemetry: anonymous per-paper open counts (no PII) ─────
    def record_view(self, paper_id: str, url: str = "", title: str = "") -> None:
        """Increment today's open-count for a paper (idempotent per UTC day bucket).

        url/title are denormalised so /api/popular can render even when the
        paper has aged out of the papers table; first non-empty value wins.
        """
        if not paper_id:
            return
        now = time.time()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO paper_views(paper_id, view_date, count, url, title, last_at) "
                    "VALUES(?,?,1,?,?,?) "
                    "ON CONFLICT(paper_id, view_date) DO UPDATE SET "
                    " count=count+1, last_at=excluded.last_at, "
                    " url=COALESCE(NULLIF(paper_views.url,''), excluded.url), "
                    " title=COALESCE(NULLIF(paper_views.title,''), excluded.title)",
                    (paper_id, today, url or "", title or "", now),
                )
        except Exception as e:
            logger.warning("paper_store: record_view failed for %s: %s", paper_id, e)

    def top_viewed(self, days: int = 7, limit: int = 40) -> list[dict[str, Any]]:
        """Most-opened papers in the trailing window, enriched from papers.payload.

        Falls back to the denormalised url/title stub when the payload was pruned.
        Stamps view_count so the frontend can sort/badge consistently.
        """
        cutoff = self._cutoff(days)
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT v.paper_id, SUM(v.count) AS views, MAX(v.url), MAX(v.title), "
                    " (SELECT payload FROM papers p WHERE p.paper_id=v.paper_id LIMIT 1) "
                    "FROM paper_views v WHERE v.view_date>=? "
                    "GROUP BY v.paper_id ORDER BY views DESC LIMIT ?",
                    (cutoff, limit),
                )
                rows = cur.fetchall()
        except Exception as e:
            logger.warning("paper_store: top_viewed failed: %s", e)
            return []
        out: list[dict[str, Any]] = []
        for pid, views, url, title, payload in rows:
            if payload:
                try:
                    p = json.loads(payload)
                except Exception:
                    p = None
            else:
                p = None
            if p is None:
                p = {"title": title or pid, "url": url or "", "authors": [],
                     "summary": "", "published": ""}
            p["view_count"] = int(views)
            out.append(p)
        return out

    def cleanup(self, max_age_days: int = 100, snapshot_age_days: int = 120) -> int:
        cutoff = self._cutoff(max_age_days)
        snap_cutoff = self._cutoff(snapshot_age_days)
        try:
            with self._lock:
                cur = self._conn.execute("DELETE FROM papers WHERE published<?", (cutoff,))
                deleted = cur.rowcount or 0
                self._conn.execute("DELETE FROM metric_snapshots WHERE snapshot_date<?", (snap_cutoff,))
                self._conn.execute("DELETE FROM topic_daily WHERE snapshot_date<?", (snap_cutoff,))
                self._conn.execute("DELETE FROM paper_views WHERE view_date<?", (snap_cutoff,))
                # papers prune by published-date but snapshots by snapshot-date — different
                # axes leave snapshots whose payload was pruned; drop those orphans so
                # get_emerging never silently skips paper_ids it can't resolve a payload for
                self._conn.execute(
                    "DELETE FROM metric_snapshots WHERE NOT EXISTS ("
                    "SELECT 1 FROM papers p WHERE p.paper_id=metric_snapshots.paper_id "
                    "AND p.primary_cat=metric_snapshots.primary_cat)"
                )
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
                snapshots = int(self._conn.execute("SELECT COUNT(*) FROM metric_snapshots").fetchone()[0])
                views = int(self._conn.execute("SELECT COALESCE(SUM(count),0) FROM paper_views").fetchone()[0])
                disk = self.db_path.stat().st_size if self.db_path.exists() else 0
            return {
                "total": total,
                "snapshots": snapshots,
                "views": views,
                "disk_bytes": disk,
                "by_cat": {c: int(n) for c, n in by_cat},
            }
        except Exception:
            return {"total": 0, "snapshots": 0, "views": 0, "disk_bytes": 0, "by_cat": {}}

    def close(self) -> None:
        try:
            with self._lock:
                self._conn.close()
        except Exception:
            pass
