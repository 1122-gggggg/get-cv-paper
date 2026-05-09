import asyncio
import unittest
from unittest.mock import patch

import userdata


class UserdataAuthTests(unittest.TestCase):
    def test_require_user_verifies_token_off_event_loop(self):
        seen = {}

        def fake_verify(token):
            seen["token"] = token
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                seen["off_event_loop"] = True
            else:
                seen["off_event_loop"] = False
            return {"sub": "user-1"}

        with patch.object(userdata, "_verify_id_token", fake_verify):
            result = asyncio.run(userdata.require_user("Bearer token-123"))

        self.assertEqual(result, {"sub": "user-1"})
        self.assertEqual(seen, {"token": "token-123", "off_event_loop": True})


if __name__ == "__main__":
    unittest.main()
