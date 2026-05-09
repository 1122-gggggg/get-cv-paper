import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import main


class ApiLimitTests(unittest.TestCase):
    def test_unique_csv_preserves_order_and_enforces_limit(self):
        self.assertEqual(main._unique_csv(" 1,2,1,,3 ", max_items=3), ["1", "2", "3"])

        with self.assertRaises(HTTPException) as ctx:
            main._unique_csv("1,2,3,4", max_items=3)

        self.assertEqual(ctx.exception.status_code, 400)

    def test_bounded_int_clamps_invalid_and_extreme_values(self):
        self.assertEqual(main._bounded_int("bad", default=7, min_value=1, max_value=10), 7)
        self.assertEqual(main._bounded_int(-50, default=7, min_value=1, max_value=10), 1)
        self.assertEqual(main._bounded_int(5000, default=7, min_value=1, max_value=10), 10)

    def test_search_clamps_upstream_max_results(self):
        seen = {}

        async def fake_search(_client, q, max_results):
            seen["q"] = q
            seen["max_results"] = max_results
            return []

        with patch.object(main, "fetch_arxiv_search", fake_search):
            result = asyncio.run(main.search_papers(" diffusion ", max_results=9999))

        self.assertEqual(result, {"papers": []})
        self.assertEqual(seen, {"q": "diffusion", "max_results": main._SEARCH_MAX_RESULTS})

    def test_pwc_rejects_too_many_ids_before_fetching(self):
        too_many = ",".join(str(i) for i in range(main._PWC_IDS_MAX + 1))

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(main.get_pwc(request=None, arxiv_ids=too_many))

        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
