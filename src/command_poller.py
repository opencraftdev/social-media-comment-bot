"""Command poller — polls Supabase bot_commands table for work triggered by the web UI."""
from __future__ import annotations

import logging
import os
import time
from typing import Callable

from supabase import create_client, Client

log = logging.getLogger(__name__)


def _get_supabase() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def poll_commands(
    run_scrape: Callable[[str], int],
    run_draft: Callable[[str], int],
    run_post_approved: Callable[[str], None],
    interval_s: int = 15,
) -> None:
    """
    Poll bot_commands table for pending work.

    Callbacks:
      run_scrape(platform)        → returns scraped_count
      run_draft(platform)         → returns drafted_count
      run_post_approved(platform) → no return value
    """
    db = _get_supabase()
    log.info("Command poller started (interval=%ds)", interval_s)

    while True:
        try:
            res = (
                db.from_("bot_commands")
                .select("*")
                .eq("status", "pending")
                .order("created_at")
                .limit(1)
                .execute()
            )
            rows = res.data or []

            if not rows:
                time.sleep(interval_s)
                continue

            cmd = rows[0]
            cmd_id = cmd["id"]
            platform = cmd.get("platform") or "all"

            db.from_("bot_commands").update({
                "status": "running",
                "started_at": "now()",
            }).eq("id", cmd_id).execute()

            log.info("Picked up command #%d: %s platform=%s", cmd_id, cmd["command"], platform)

            try:
                context: dict = {}
                if cmd["command"] == "scrape":
                    context["scraped_count"] = run_scrape(platform)
                elif cmd["command"] == "draft":
                    context["drafted_count"] = run_draft(platform)
                elif cmd["command"] == "post_approved":
                    run_post_approved(platform)
                else:
                    log.warning("Unknown command: %s", cmd["command"])

                db.from_("bot_commands").update({
                    "status": "done",
                    "finished_at": "now()",
                    "context": context,
                }).eq("id", cmd_id).execute()
                log.info("Command #%d done context=%s", cmd_id, context)

            except Exception as e:
                db.from_("bot_commands").update({
                    "status": "failed",
                    "error": str(e)[:500],
                    "finished_at": "now()",
                }).eq("id", cmd_id).execute()
                log.error("Command #%d failed: %s", cmd_id, e)

        except Exception as e:
            log.error("Poller error: %s", e)
            time.sleep(interval_s)
