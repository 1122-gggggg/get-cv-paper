"""In-process SSE pub/sub hub for a single-worker FastAPI deployment.

Fans out small JSON events (e.g. "new papers landed for discipline X") to every
connected browser tab via Server-Sent Events. Bounded by design for a free-tier
VM: caps concurrent subscribers and gives each a bounded queue that drops its
oldest event on overflow, so one slow/stalled tab can never wedge a publisher.

publish() is synchronous and dispatches onto each subscriber's owning event
loop when called from another thread. Subscribers created without a running
loop retain the legacy direct-delivery behavior.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_MAX_SUBSCRIBERS = 500   # 同時連線上限,擋住資源耗盡
_QUEUE_MAXSIZE = 32      # 每個 tab 的事件緩衝;溢位丟最舊


class EventHub:
    """Broadcast hub holding one bounded asyncio.Queue per subscribed tab."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subs: dict[
            asyncio.Queue[dict[str, Any]],
            asyncio.AbstractEventLoop | None,
        ] = {}

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]] | None:
        """Register a new subscriber. Returns None when at capacity."""
        try:
            owner_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            owner_loop = None

        with self._lock:
            if len(self._subs) >= _MAX_SUBSCRIBERS:
                return None
            q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
            self._subs[q] = owner_loop
            return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subs.pop(q, None)

    def _deliver(
        self,
        q: asyncio.Queue[dict[str, Any]],
        event: dict[str, Any],
    ) -> None:
        """Deliver on the subscriber's owner loop if it is still registered."""
        with self._lock:
            if q not in self._subs:
                return
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def publish(self, event: dict[str, Any]) -> None:
        """Fan out one event, marshalling cross-thread delivery onto owner loops."""
        with self._lock:
            subscribers = tuple(self._subs.items())

        try:
            current_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        for q, owner_loop in subscribers:
            # Events are small JSON-style mappings. Deep-copy them so a slow
            # consumer cannot observe mutations by the caller or another tab.
            payload = copy.deepcopy(event)
            if owner_loop is None or owner_loop is current_loop:
                self._deliver(q, payload)
                continue
            try:
                owner_loop.call_soon_threadsafe(self._deliver, q, payload)
            except RuntimeError:
                # The subscriber loop has already closed; remove the stale queue.
                self.unsubscribe(q)
