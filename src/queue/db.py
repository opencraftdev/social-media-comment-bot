"""Supabase queue — replaces SQLite. Same public API, all writes go to Supabase `replies` table."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv
from supabase import create_client, Client

# Kept for backward-compat (cmd_status prints it)
DB_PATH = "supabase (remote)"


def _db() -> Client:
    load_dotenv()
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_range() -> tuple[str, str]:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    return today.isoformat() + "T00:00:00+00:00", tomorrow.isoformat() + "T00:00:00+00:00"


# --------------------------------------------------------------------------- #
# Schema / init
# --------------------------------------------------------------------------- #

def init_db() -> None:
    """No-op — table is managed in Supabase dashboard."""
    pass


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #

def list_items(
    status: str | None = None,
    platform: str = "all",
    limit: int = 20,
) -> list[dict[str, Any]]:
    q = _db().from_("replies").select("*")
    if status:
        q = q.eq("status", status)
    if platform and platform != "all":
        q = q.eq("platform", platform)
    res = q.order("id", desc=True).limit(limit).execute()
    return res.data or []


def count_today(platform: str | None = None, status: str | None = None) -> int:
    start, end = _today_range()
    q = _db().from_("replies").select("*", count="exact")
    if status == "posted":
        q = q.gte("posted_at", start).lt("posted_at", end)
    elif status:
        q = q.eq("status", status)
    if platform and platform != "all":
        q = q.eq("platform", platform)
    res = q.execute()
    return res.count or 0


def get_item(item_id: int) -> dict[str, Any] | None:
    res = _db().from_("replies").select("*").eq("id", item_id).limit(1).execute()
    return res.data[0] if res.data else None


def has_replied(platform: str, account: str, parent_post_id: str) -> bool:
    res = (
        _db().from_("replies")
        .select("id", count="exact")
        .eq("platform", platform)
        .eq("account_username", account)
        .eq("parent_post_id", parent_post_id)
        .in_("status", ["posted", "approved"])
        .execute()
    )
    return (res.count or 0) > 0


def last_scrape_at(platform: str | None = None) -> str | None:
    q = _db().from_("replies").select("scraped_at")
    if platform:
        q = q.eq("platform", platform)
    res = q.order("scraped_at", desc=True).limit(1).execute()
    return res.data[0]["scraped_at"] if res.data else None


def queue_counts() -> dict[tuple[str, str], int]:
    res = _db().from_("replies").select("platform,status").execute()
    counts: dict[tuple[str, str], int] = {}
    for row in (res.data or []):
        key = (row["platform"], row["status"])
        counts[key] = counts.get(key, 0) + 1
    return counts


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #

def insert_scraped(
    platform: str,
    account_username: str,
    parent_post_id: str,
    parent_post_url: str,
    parent_post_text: str,
    parent_author: str,
    parent_likes: int = 0,
    parent_replies: int = 0,
    parent_created_at: Any = None,
    note: str | None = None,
) -> int | None:
    """Insert a freshly scraped post. Returns row id, or None on duplicate."""
    if parent_created_at is not None and hasattr(parent_created_at, "isoformat"):
        parent_created_at = parent_created_at.isoformat()

    row = {
        "platform": platform,
        "account_username": account_username,
        "parent_post_id": parent_post_id,
        "parent_post_url": parent_post_url,
        "parent_post_text": parent_post_text,
        "parent_author": parent_author,
        "parent_likes": parent_likes,
        "parent_replies": parent_replies,
        "parent_created_at": parent_created_at,
        "status": "scraped",
        "note": note,
        "scraped_at": _now(),
    }

    res = (
        _db().from_("replies")
        .upsert(row, on_conflict="platform,account_username,parent_post_id", ignore_duplicates=True)
        .execute()
    )
    # Returns data only on insert (not on ignored duplicate)
    return res.data[0]["id"] if res.data else None


def set_status(item_id: int, new_status: str, note: str | None = None) -> None:
    ts_map = {
        "approved": "approved_at",
        "posted": "posted_at",
        "ready_for_review": "drafted_at",
    }
    update: dict[str, Any] = {"status": new_status}
    ts_col = ts_map.get(new_status)
    if ts_col:
        update[ts_col] = _now()
    if note is not None:
        update["note"] = note
    _db().from_("replies").update(update).eq("id", item_id).execute()


def save_draft(item_id: int, reply_mode: str, draft_text: str) -> None:
    _db().from_("replies").update({
        "reply_mode": reply_mode,
        "draft_text": draft_text,
        "status": "ready_for_review",
        "drafted_at": _now(),
        "error": None,
    }).eq("id", item_id).execute()


def mark_draft_failed(item_id: int, error: str) -> None:
    _db().from_("replies").update({
        "status": "failed",
        "error": f"draft: {error[:300]}",
    }).eq("id", item_id).execute()


def mark_posted(
    item_id: int,
    reply_platform_id: str,
    reply_url: str | None = None,
    final_text: str | None = None,
) -> None:
    update: dict[str, Any] = {
        "status": "posted",
        "reply_platform_id": reply_platform_id,
        "reply_url": reply_url,
        "posted_at": _now(),
        "error": None,
    }
    if final_text is not None:
        update["final_text"] = final_text
    _db().from_("replies").update(update).eq("id", item_id).execute()


def mark_post_failed(item_id: int, error: str) -> None:
    _db().from_("replies").update({
        "status": "failed",
        "error": f"post: {error[:500]}",
    }).eq("id", item_id).execute()
