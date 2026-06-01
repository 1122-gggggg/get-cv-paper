"""VAPID Web-Push wrapper (#19).

Gated on env keys + pywebpush availability: if either is missing the service
reports ``enabled=False`` and every send is a no-op, so the app boots and
serves normally without push configured.

Activation (on the host, not committed):
    pip install py-vapid pywebpush
    vapid --gen                         # private_key.pem / public_key.pem
    vapid --applicationServerKey        # base64url public key for the browser
Then set env: VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY (PEM or base64url),
VAPID_SUBJECT (mailto:you@example.com).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

try:
    from pywebpush import WebPushException, webpush

    _PYWEBPUSH_OK = True
except ImportError:  # library not installed → feature stays disabled
    webpush = None  # type: ignore[assignment]
    WebPushException = Exception  # type: ignore[assignment,misc]
    _PYWEBPUSH_OK = False


class PushService:
    """Singleton-ish holder for VAPID config + blocking send.

    ``send`` is synchronous (pywebpush uses ``requests``); call it from a
    thread (``asyncio.to_thread``) on the server side.
    """

    def __init__(self) -> None:
        self._public = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
        self._private = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
        subject = (os.environ.get("VAPID_SUBJECT") or "").strip()
        # PEM provided with escaped newlines in .env → restore real newlines.
        if "BEGIN" in self._private and "\\n" in self._private:
            self._private = self._private.replace("\\n", "\n")
        self._claims_sub = subject or "mailto:admin@allenvisionary.duckdns.org"
        self.enabled = bool(self._public and self._private and _PYWEBPUSH_OK)
        if not _PYWEBPUSH_OK:
            logger.info("webpush: pywebpush not installed — push disabled")
        elif not self.enabled:
            logger.info("webpush: VAPID keys absent — push disabled")
        else:
            logger.info("webpush: enabled")

    @property
    def public_key(self) -> str:
        return self._public

    def send(self, subscription_info: dict, data: str) -> int:
        """Send one push. Returns HTTP status (201/200 ok; 404/410 → prune; 0 = skipped/error)."""
        if not self.enabled or webpush is None:
            return 0
        try:
            resp = webpush(
                subscription_info=subscription_info,
                data=data,
                vapid_private_key=self._private,
                vapid_claims={"sub": self._claims_sub},
                ttl=86400,
            )
            return getattr(resp, "status_code", 201)
        except WebPushException as e:  # type: ignore[misc]
            status = getattr(getattr(e, "response", None), "status_code", 0) or 0
            if status not in (404, 410):
                logger.warning("webpush: send failed (status=%s): %s", status, e)
            return status
        except Exception as e:  # network/encoding — don't crash the loop
            logger.warning("webpush: unexpected send error: %s", e)
            return 0


push_service = PushService()
