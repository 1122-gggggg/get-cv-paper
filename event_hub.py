"""In-process SSE pub/sub hub for a single-worker FastAPI deployment.

Fans out small JSON events (e.g. "new papers landed for discipline X") to every
connected browser tab via Server-Sent Events. Bounded by design for a free-tier
VM: caps concurrent subscribers and gives each a bounded queue that drops its
oldest event on overflow, so one slow/stalled tab can never wedge a publisher.

publish() is synchronous (put_nowait only) so it is callable from any context —
background loops or request-path cache builds — without awaiting.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_SUBSCRIBERS = 500   # 同時連線上限,擋住資源耗盡
_QUEUE_MAXSIZE = 32      # 每個 tab 的事件緩衝;溢位丟最舊


class EventHub:
    """Broadcast hub holding one bounded asyncio.Queue per subscribed tab."""

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue[dict[str, Any]]] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]] | None:
        """Register a new subscriber. Returns None when at capacity."""
        if len(self._subs) >= _MAX_SUBSCRIBERS:
            return None
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        """Fan out one event to all subscribers. Drops oldest on a full queue."""
        for q in list(self._subs):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
