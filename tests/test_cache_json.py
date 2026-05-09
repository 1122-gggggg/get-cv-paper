import asyncio
import unittest

from cache import CachedJSON


class CacheJsonTests(unittest.TestCase):
    def test_cached_json_serializes_compact_payloads(self):
        cache = CachedJSON(ttl=60)

        async def build():
            return {"papers": [{"title": "A", "count": 1}]}

        body, _etag = asyncio.run(cache.get_or_build("k", build))

        self.assertEqual(body, b'{"papers":[{"title":"A","count":1}]}')


if __name__ == "__main__":
    unittest.main()
