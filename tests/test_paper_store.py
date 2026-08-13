"""Time-series snapshot / burst-delta contract for PaperStore."""
import tempfile
import unittest
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from paper_store import PaperStore, _paper_id


def _d(offset: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=offset)).strftime("%Y-%m-%d")


class PaperStoreSnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = PaperStore(Path(self._tmp.name) / "t.sqlite")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def _paper(self, aid, cit=None, hf=None, pub=None, stars=None, gh=None):
        p = {"title": f"P{aid}", "url": f"https://arxiv.org/abs/{aid}",
             "external_ids": {"arxiv": aid}}
        if cit is not None:
            p["citation_count"] = cit
        if hf is not None:
            p["hf_upvotes"] = hf
        if pub is not None:
            p["published"] = pub
        if stars is not None:
            p["github_stars"] = stars
        if gh is not None:
            p["github_url"] = gh
        return p

    def test_record_snapshots_writes_and_counts(self):
        papers = [self._paper("2401.1", cit=5, hf=2, pub=_d(0)),
                  self._paper("2401.2", cit=0, pub=_d(40))]
        n = self.store.record_snapshots(papers, "ml")
        self.assertEqual(n, 2)
        series = self.store.topic_volume_series("ml", days=3)
        self.assertEqual(series[-1]["paper_count"], 2)
        self.assertEqual(series[-1]["fresh_count"], 1)  # only 2401.1 is recent

    def test_same_day_rebuild_takes_max(self):
        self.store.record_snapshots([self._paper("2401.1", cit=5)], "ml")
        # later same-day build carries enriched citations
        self.store.record_snapshots([self._paper("2401.1", cit=50)], "ml")
        # inject an older snapshot directly so a delta exists
        with self.store._lock:
            self.store._conn.execute(
                "INSERT INTO metric_snapshots(paper_id, primary_cat, snapshot_date, "
                "citation_count, hf_upvotes, published, at) VALUES(?,?,?,?,?,?,?)",
                (_paper_id(self._paper("2401.1")), "ml", _d(7), 10, 0, "", 0.0),
            )
        deltas = self.store.metric_deltas("ml", window_days=14)
        self.assertEqual(len(deltas), 1)
        d = deltas[0]
        self.assertEqual(d["cit_new"], 50)  # max of same-day readings
        self.assertEqual(d["cit_old"], 10)

    def test_metric_deltas_requires_two_dates(self):
        # single-day snapshot → no delta row
        self.store.record_snapshots([self._paper("2401.9", cit=3)], "ml")
        self.assertEqual(self.store.metric_deltas("ml", window_days=14), [])

    def test_payloads_by_ids_roundtrip(self):
        p = self._paper("2401.5", cit=7, pub=_d(1))
        self.store.upsert_many([p], "ml")
        got = self.store.payloads_by_ids([_paper_id(p)], "ml")
        self.assertIn(_paper_id(p), got)
        self.assertEqual(got[_paper_id(p)]["citation_count"], 7)

    def test_github_stars_snapshot_delta(self):
        # star 補值寫進 snapshots,metric_deltas 暴露 new/old star
        self.store.record_snapshots([self._paper("2401.7", stars=120)], "ml")
        with self.store._lock:
            self.store._conn.execute(
                "INSERT INTO metric_snapshots(paper_id, primary_cat, snapshot_date, "
                "github_stars, published, at) VALUES(?,?,?,?,?,?)",
                (_paper_id(self._paper("2401.7")), "ml", _d(7), 30, "", 0.0),
            )
        d = self.store.metric_deltas("ml", window_days=14)[0]
        self.assertEqual(d["star_new"], 120)
        self.assertEqual(d["star_old"], 30)

    def test_github_urls_for_arxiv_lookup(self):
        p = self._paper("2401.8", pub=_d(1), gh="https://github.com/foo/bar")
        self.store.upsert_many([p], "ml")
        got = self.store.github_urls_for_arxiv(["2401.8", "2401.404"])
        self.assertEqual(got, {"2401.8": "https://github.com/foo/bar"})



class _ProbeLock:
    """Runs one concurrent reader after a failing transaction releases its lock."""

    def __init__(self):
        self._lock = threading.Lock()
        self.released = threading.Event()
        self.observed = threading.Event()
        self._armed = True

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._lock.release()
        if self._armed and exc_type is not None:
            self._armed = False
            self.released.set()
            self.observed.wait(timeout=2)
        return False


class PaperStoreTransactionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = PaperStore(Path(self._tmp.name) / "transaction.sqlite")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    @staticmethod
    def _paper(aid):
        return {
            "title": f"Paper {aid}",
            "url": f"https://arxiv.org/abs/{aid}",
            "external_ids": {"arxiv": aid},
        }

    def test_failed_upsert_is_rolled_back_before_other_thread_can_read_it(self):
        self.store._conn.execute(
            """
            CREATE TRIGGER fail_meta_insert
            BEFORE INSERT ON meta
            WHEN NEW.primary_cat = 'broken'
            BEGIN
                SELECT RAISE(ABORT, 'forced meta failure');
            END;
            """
        )
        probe = _ProbeLock()
        self.store._lock = probe
        observed: list[int] = []

        def observe_after_release():
            probe.released.wait(timeout=2)
            observed.append(self.store.stats()["total"])
            probe.observed.set()

        reader = threading.Thread(target=observe_after_release)
        reader.start()
        self.assertEqual(self.store.upsert_many([self._paper("2401.00001")], "broken"), 0)
        reader.join(timeout=2)

        self.assertFalse(reader.is_alive())
        self.assertEqual(observed, [0])
        with self.store._lock:
            meta_rows = self.store._conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0]
        self.assertEqual(meta_rows, 0)
        self.assertEqual(self.store.upsert_many([self._paper("2401.00002")], "safe"), 1)

    def test_failed_snapshot_write_leaves_no_partial_snapshot_rows(self):
        self.store._conn.execute(
            """
            CREATE TRIGGER fail_topic_insert
            BEFORE INSERT ON topic_daily
            WHEN NEW.primary_cat = 'broken'
            BEGIN
                SELECT RAISE(ABORT, 'forced topic failure');
            END;
            """
        )
        self.assertEqual(self.store.record_snapshots([self._paper("2401.00003")], "broken"), 0)
        self.assertEqual(self.store.stats()["snapshots"], 0)
        with self.store._lock:
            topic_rows = self.store._conn.execute("SELECT COUNT(*) FROM topic_daily").fetchone()[0]
        self.assertEqual(topic_rows, 0)
        self.assertEqual(self.store.record_snapshots([self._paper("2401.00004")], "safe"), 1)


class PaperStoreViewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = PaperStore(Path(self._tmp.name) / "v.sqlite")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_record_view_accumulates_and_ranks(self):
        self.store.record_view("arxiv:2401.1", "https://a/1", "P1")
        self.store.record_view("arxiv:2401.1", "https://a/1", "P1")
        self.store.record_view("arxiv:2401.2", "https://a/2", "P2")
        top = self.store.top_viewed(days=7, limit=10)
        self.assertEqual(top[0]["view_count"], 2)
        self.assertEqual(top[0]["url"], "https://a/1")
        self.assertEqual([p["view_count"] for p in top], [2, 1])

    def test_top_viewed_enriches_from_payload(self):
        p = {"title": "Real", "url": "https://arxiv.org/abs/2401.5",
             "summary": "full abstract", "external_ids": {"arxiv": "2401.5"}}
        self.store.upsert_many([p], "ml")
        self.store.record_view(_paper_id(p), p["url"], p["title"])
        top = self.store.top_viewed(days=7, limit=10)
        self.assertEqual(top[0]["summary"], "full abstract")  # payload, not stub
        self.assertEqual(top[0]["view_count"], 1)

    def test_top_viewed_falls_back_to_stub_when_payload_pruned(self):
        self.store.record_view("arxiv:2401.9", "https://a/9", "Stub Title")
        top = self.store.top_viewed(days=7, limit=10)
        self.assertEqual(top[0]["title"], "Stub Title")
        self.assertEqual(top[0]["url"], "https://a/9")
        self.assertEqual(top[0]["summary"], "")

    def test_record_view_ignores_empty_id(self):
        self.store.record_view("", "https://a/x", "x")
        self.assertEqual(self.store.top_viewed(days=7), [])

    def test_stats_reports_view_total(self):
        self.store.record_view("arxiv:2401.1")
        self.store.record_view("arxiv:2401.1")
        self.assertEqual(self.store.stats()["views"], 2)


if __name__ == "__main__":
    unittest.main()
