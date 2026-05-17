"""Monkey-patch for twikit's broken transaction-id generation.

X (Nov 2025) changed their on-demand JS minifier, breaking twikit's INDICES_REGEX
extraction. Result: every twikit API call raises "Couldn't get KEY_BYTE indices".

Workaround: bypass the transaction-id pipeline entirely. For authenticated
read/write calls with valid cookies, X tolerates missing X-Client-Transaction-Id
in many endpoints (search, statuses/create). Heavy automated scraping may still
trip rate limits — keep volume low.

Import this module BEFORE creating any twikit Client.
"""
from __future__ import annotations

try:
    from twikit.x_client_transaction import transaction as _tx
except ImportError:
    _tx = None


_PATCHED = False


def patch_twikit() -> None:
    global _PATCHED
    if _PATCHED or _tx is None:
        return

    async def _init_noop(self, session, headers):
        # Sentinel so the per-request guard in client.py considers this initialized.
        self.home_page_response = object()
        self.DEFAULT_ROW_INDEX = 0
        self.DEFAULT_KEY_BYTES_INDICES = []
        self.key = ""
        self.key_bytes = b""
        self.animation_key = ""

    def _generate_noop(self, method=None, path=None, *args, **kwargs):
        return ""

    _tx.ClientTransaction.init = _init_noop
    _tx.ClientTransaction.generate_transaction_id = _generate_noop
    _PATCHED = True
