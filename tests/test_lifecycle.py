import asyncio
import logging
import threading
import unittest
from unittest.mock import patch

from fastapi import FastAPI

import main


class _RecorderStore:
    def __init__(self, name, order, started):
        self.name = name
        self.order = order
        self.started = started

    def flush(self):
        self.order.append(f"{self.name}.flush")
        self.started.set()


class _RecorderPaperStore:
    def __init__(self, order):
        self.order = order

    def close(self):
        self.order.append("paper_store.close")


class _RecorderHttpClient:
    def __init__(self, order):
        self.order = order

    async def aclose(self):
        self.order.append("http_client.close")


class _RecorderSink:
    def __init__(self, order):
        self.order = order

    async def aclose(self):
        self.order.append("betterstack.close")


class LifespanShutdownTests(unittest.TestCase):
    def test_shutdown_awaits_background_tasks_before_closing_resources(self):
        async def scenario():
            names = ("flush", "warm", "warm_t2", "cleanup", "stars", "oai")
            started: set[str] = set()
            cancelled: set[str] = set()
            started_all = asyncio.Event()
            cancelled_all = asyncio.Event()
            finish_cancel = asyncio.Event()
            order: list[str] = []
            flush_started = threading.Event()

            async def background(name):
                started.add(name)
                if len(started) == len(names):
                    started_all.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.add(name)
                    if len(cancelled) == len(names):
                        cancelled_all.set()
                    await finish_cancel.wait()
                    order.append(f"cancel:{name}")
                    raise

            s2_store = _RecorderStore("s2", order, flush_started)
            pwc_store = _RecorderStore("pwc", order, flush_started)
            paper_store = _RecorderPaperStore(order)
            http_client = _RecorderHttpClient(order)
            sink = _RecorderSink(order)
            old_s2 = main._s2_store
            old_pwc = main._pwc_store
            old_paper_store = main._paper_store
            old_http_client = main._http_client
            old_index_html = main._INDEX_HTML
            try:
                main._s2_store = s2_store
                main._pwc_store = pwc_store
                main._paper_store = paper_store
                main._http_client = http_client
                with (
                    patch.object(main, "_flush_task", lambda: background("flush")),
                    patch.object(main, "_warmup_loop", lambda: background("warm")),
                    patch.object(main, "_warmup_loop_tier2", lambda: background("warm_t2")),
                    patch.object(main, "_paper_cleanup_task", lambda: background("cleanup")),
                    patch.object(main, "_stars_loop", lambda: background("stars")),
                    patch.object(main, "_oai_harvest_loop", lambda: background("oai")),
                    patch.object(main, "_OAI_ENABLED", True),
                    patch.object(main, "_OAI_SETS", ("cs",)),
                    patch.object(main, "_betterstack_handler", sink, create=True),
                ):
                    manager = main.lifespan(FastAPI())
                    await manager.__aenter__()
                    await asyncio.wait_for(started_all.wait(), timeout=1)
                    closing = asyncio.create_task(manager.__aexit__(None, None, None))
                    await asyncio.wait_for(cancelled_all.wait(), timeout=1)
                    premature_flush = await asyncio.to_thread(flush_started.wait, 0.05)
                    finish_cancel.set()
                    await closing
            finally:
                main._s2_store = old_s2
                main._pwc_store = old_pwc
                main._paper_store = old_paper_store
                main._http_client = old_http_client
                main._INDEX_HTML = old_index_html

            self.assertFalse(premature_flush)
            self.assertEqual(cancelled, set(names))
            first_resource = order.index("s2.flush")
            self.assertTrue(all(order.index(f"cancel:{name}") < first_resource for name in names))
            self.assertEqual(
                order[first_resource:],
                ["s2.flush", "pwc.flush", "paper_store.close", "http_client.close", "betterstack.close"],
            )

        asyncio.run(scenario())


class BetterStackHandlerTests(unittest.TestCase):
    def test_aclose_drains_ship_task_before_closing_client(self):
        async def scenario():
            order: list[str] = []
            allow_post = asyncio.Event()

            class Client:
                async def post(self, _endpoint, json):
                    order.append("post")
                    await allow_post.wait()
                    order.append("shipped")

                async def aclose(self):
                    order.append("client.close")

            client = Client()
            with patch("httpx.AsyncClient", return_value=client):
                handler = main._BetterStackHandler("token")
            record = logging.LogRecord("test", logging.ERROR, __file__, 0, "boom", (), None)
            handler.emit(record)
            await asyncio.sleep(0)
            self.assertEqual(len(handler._ship_tasks), 1)

            closing = asyncio.create_task(handler.aclose())
            await asyncio.sleep(0)
            self.assertNotIn("client.close", order)
            allow_post.set()
            await closing

            self.assertEqual(order, ["post", "shipped", "client.close"])
            self.assertEqual(handler._ship_tasks, set())

        asyncio.run(scenario())
    def test_aclose_rejects_emit_after_closing_begins(self):
        async def scenario():
            order: list[str] = []
            first_started = asyncio.Event()
            late_started = asyncio.Event()
            allow_first = asyncio.Event()
            allow_late = asyncio.Event()

            class Client:
                async def post(self, _endpoint, json):
                    message = json["message"]
                    order.append(f"post:{message}")
                    if message == "first":
                        first_started.set()
                        await allow_first.wait()
                    else:
                        late_started.set()
                        await allow_late.wait()
                    order.append(f"shipped:{message}")

                async def aclose(self):
                    order.append("client.close")

            with patch("httpx.AsyncClient", return_value=Client()):
                handler = main._BetterStackHandler("token")
            root = logging.getLogger()
            root.addHandler(handler)
            closing: asyncio.Task[None] | None = None
            try:
                handler.emit(logging.LogRecord("test", logging.ERROR, __file__, 0, "first", (), None))
                await asyncio.wait_for(first_started.wait(), timeout=1)
                closing = asyncio.create_task(handler.aclose())
                await asyncio.sleep(0)
                handler.emit(logging.LogRecord("test", logging.ERROR, __file__, 0, "late", (), None))
                await asyncio.sleep(0)
                allow_first.set()
                await closing

                self.assertFalse(late_started.is_set())
                self.assertEqual(order, ["post:first", "shipped:first", "client.close"])
                self.assertNotIn(handler, root.handlers)
            finally:
                root.removeHandler(handler)
                allow_first.set()
                allow_late.set()
                if closing is not None and not closing.done():
                    await closing
                await asyncio.sleep(0)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
