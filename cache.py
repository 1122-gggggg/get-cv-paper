"""Bounded LRU + TTL store, plus a cached-JSON response helper.

The CachedJSON class owns: TTL eviction, body-bytes memoization, ETag
generation, single-flight, and 304 short-circuit. Handlers just provide a
cache key and a builder coroutine.
"""
from __future__ import annotations

import asyncio
import hashlib
import json as _json
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import Request
from fastapi.responses import Response

logger = logging.getLogger(__name__)


class LRUStore:
    """Per-key LRU with TTL and optional JSON persistence on disk."""

    def __init__(
        self,
        name: str,
        maxsize: int,
        ttl: float,
        cache_dir: Path | None = None,
        persist: bool = True,
    ):
        self.name = name
        self.maxsize = maxsize
        self.ttl = ttl
        self.persist = persist and cache_dir is not None
        self.path: Path | None = (cache_dir / f"{name}.json") if cache_dir else None
        self._data: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self.persist or self.path is None or not self.path.exists():
            return
        try:
            raw = _json.loads(self.path.read_text("utf-8"))
            if isinstance(raw, dict):
                self._data = OrderedDict(raw)
        except Exception as e:
            logger.warning("cache %s load failed: %s", self.name, e)

    def flush(self) -> None:
        if not self.persist or not self._dirty or self.path is None:
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


def make_etag(payload: bytes) -> str:
    return 'W/"' + hashlib.md5(payload).hexdigest()[:16] + '"'


_DEFAULT_CACHE_HEADERS = {"Cache-Control": "public, max-age=60, must-revalidate"}


def etag_response(
    request: Request,
    body: bytes,
    etag: str,
    extra_headers: dict[str, str] | None = None,
) -> Response:
    """Return 304 on If-None-Match match, else a JSON Response with ETag."""
    headers = dict(_DEFAULT_CACHE_HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    headers["ETag"] = etag
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


class CachedJSON:
    """Keyed cache of (body bytes, ETag) with TTL + optional stale-while-revalidate.

    - fresh window  (age < ttl): return cached, no work
    - stale window  (ttl < age < ttl + stale_ttl): return cached immediately,
      kick off background revalidation (single-flight per key)
    - expired       (age > ttl + stale_ttl): wait for builder

    On builder failure during background refresh: keeps old entry intact
    (stale-on-error). On synchronous build failure with no cache: raises.

    `get_or_build(key, builder)` either returns cached (body, etag) or runs
    the builder once for all concurrent callers waiting on the same key.
    The builder returns a JSON-serialisable Python object.
    """

    def __init__(self, ttl: float, max_keys: int = 64, stale_ttl: float = 0):
        self.ttl = ttl
        self.stale_ttl = stale_ttl
        self.max_keys = max_keys
        self._entries: "OrderedDict[str, tuple[float, bytes, str]]" = OrderedDict()
        self._inflight: dict[str, asyncio.Future] = {}
        # 計數:供 /api/metrics 觀測 cache 效益
        self.metrics: dict[str, int] = {
            "hit_fresh": 0, "hit_stale": 0, "miss": 0,
            "build_ok": 0, "build_err": 0, "warm_ok": 0, "warm_skip": 0,
        }

    # ── primitive lookups ────────────────────────────────────────
    def _get_entry(self, key: str) -> tuple[float, bytes, str] | None:
        ent = self._entries.get(key)
        if ent is None:
            return None
        at, _, _ = ent
        age = time.time() - at
        if age > self.ttl + self.stale_ttl:
            self._entries.pop(key, None)
            return None
        self._entries.move_to_end(key)
        return ent

    def _is_fresh(self, at: float) -> bool:
        return (time.time() - at) <= self.ttl

    def _store(self, key: str, body: bytes, etag: str) -> None:
        self._entries[key] = (time.time(), body, etag)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_keys:
            self._entries.popitem(last=False)

    # ── single-flight build ─────────────────────────────────────
    async def _build(
        self,
        key: str,
        builder: Callable[[], Awaitable[Any]],
    ) -> tuple[bytes, str]:
        inflight = self._inflight.get(key)
        if inflight is not None:
            return await inflight

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._inflight[key] = fut
        try:
            payload = await builder()
            body = _json.dumps(payload, ensure_ascii=False).encode("utf-8")
            etag = make_etag(body)
            self._store(key, body, etag)
            self.metrics["build_ok"] += 1
            fut.set_result((body, etag))
            return body, etag
        except BaseException as e:
            self.metrics["build_err"] += 1
            fut.set_exception(e)
            raise
        finally:
            self._inflight.pop(key, None)

    def _bg_refresh(self, key: str, builder: Callable[[], Awaitable[Any]]) -> None:
        """Fire-and-forget background revalidation. Errors are logged, not raised."""
        if key in self._inflight:
            return  # 已有同 key build 進行中

        async def _runner() -> None:
            try:
                await self._build(key, builder)
            except Exception as e:
                logger.warning("SWR background refresh failed for %s: %s", key, e)

        try:
            asyncio.get_running_loop().create_task(_runner())
        except RuntimeError:
            pass  # 無 running loop（不該發生在 request 路徑）

    async def get_or_build(
        self,
        key: str,
        builder: Callable[[], Awaitable[Any]],
    ) -> tuple[bytes, str]:
        ent = self._get_entry(key)
        if ent is not None:
            at, body, etag = ent
            if self._is_fresh(at):
                self.metrics["hit_fresh"] += 1
                return body, etag
            # stale-while-revalidate: 立刻回舊資料,背景刷新
            self.metrics["hit_stale"] += 1
            self._bg_refresh(key, builder)
            return body, etag

        self.metrics["miss"] += 1
        return await self._build(key, builder)

    async def warm(self, key: str, builder: Callable[[], Awaitable[Any]]) -> None:
        """Force a build for warmup. Skips if a fresh entry already exists."""
        ent = self._get_entry(key)
        if ent is not None and self._is_fresh(ent[0]):
            self.metrics["warm_skip"] += 1
            return
        try:
            await self._build(key, builder)
            self.metrics["warm_ok"] += 1
        except Exception as e:
            logger.warning("warmup failed for %s: %s", key, e)

    def stats(self) -> dict[str, Any]:
        m = dict(self.metrics)
        total_hits = m["hit_fresh"] + m["hit_stale"]
        total = total_hits + m["miss"]
        m["hit_rate"] = (total_hits / total) if total else 0.0
        m["entries"] = len(self._entries)
        m["inflight"] = len(self._inflight)
        return m
