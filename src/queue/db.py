"""SQLite queue — dedup + audit + approval state."""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "bot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,                -- 'threads' | 'x'
    account_username TEXT NOT NULL,
    parent_post_id TEXT NOT NULL,
    parent_post_url TEXT,
    parent_post_text TEXT,
    parent_author TEXT,
    parent_likes INTEGER,
    parent_replies INTEGER,
    parent_created_at TIMESTAMP,           -- when the TARGET post was published
    reply_mode TEXT,                       -- agree_and_extend | polite_contrarian | ...
    draft_text TEXT,
    final_text TEXT,
    reply_platform_id TEXT,                -- ID returned by platform on publish
    reply_url TEXT,                        -- permalink to the published reply
    status TEXT NOT NULL DEFAULT 'scraped',
    error TEXT,
    note TEXT,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    drafted_at TIMESTAMP,
    approved_at TIMESTAMP,
    posted_at TIMESTAMP,
    UNIQUE(platform, account_username, parent_post_id)
);

CREATE INDEX IF NOT EXISTS idx_replies_status         ON replies(status);
CREATE INDEX IF NOT EXISTS idx_replies_platform       ON replies(platform);
CREATE INDEX IF NOT EXISTS idx_replies_posted_at      ON replies(posted_at);
CREATE INDEX IF NOT EXISTS idx_replies_scraped_at     ON replies(scraped_at);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _ensure_column(c: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    rows = c.execute(f"PRAGMA table_info('{table}')").fetchall()
    if not any(r["name"] == column for r in rows):
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)
        # Forward-compatible migrations for existing DBs
        _ensure_column(c, "replies", "parent_created_at", "TIMESTAMP")
        _ensure_column(c, "replies", "reply_url", "TEXT")


def list_items(
    status: str | None = None,
    platform: str = "all",
    limit: int = 20,
) -> list[dict[str, Any]]:
    q = "SELECT * FROM replies WHERE 1=1"
    args: list[Any] = []
    if status:
        q += " AND status = ?"
        args.append(status)
    if platform and platform != "all":
        q += " AND platform = ?"
        args.append(platform)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)

    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    return [dict(r) for r in rows]


def count_today(platform: str | None = None, status: str | None = None) -> int:
    today = date.today().isoformat()
    q = "SELECT COUNT(*) AS n FROM replies WHERE date(posted_at) = ?" if status == "posted" \
        else "SELECT COUNT(*) AS n FROM replies WHERE 1=1"
    args: list[Any] = [today] if status == "posted" else []
    if status and status != "posted":
        q += " AND status = ?"
        args.append(status)
    if platform and platform != "all":
        q += " AND platform = ?"
        args.append(platform)

    with _conn() as c:
        row = c.execute(q, args).fetchone()
    return row["n"] if row else 0


def set_status(item_id: int, new_status: str, note: str | None = None) -> None:
    ts_col = {
        "approved": "approved_at",
        "posted": "posted_at",
        "ready_for_review": "drafted_at",
    }.get(new_status)
    fields = ["status = ?"]
    args: list[Any] = [new_status]
    if ts_col:
        fields.append(f"{ts_col} = CURRENT_TIMESTAMP")
    if note is not None:
        fields.append("note = ?")
        args.append(note)
    args.append(item_id)
    with _conn() as c:
        c.execute(f"UPDATE replies SET {', '.join(fields)} WHERE id = ?", args)


def save_draft(item_id: int, reply_mode: str, draft_text: str) -> None:
    """Persist a generated draft and advance status to ready_for_review."""
    with _conn() as c:
        c.execute(
            "UPDATE replies SET reply_mode = ?, draft_text = ?, "
            "status = 'ready_for_review', drafted_at = CURRENT_TIMESTAMP, "
            "error = NULL WHERE id = ?",
            (reply_mode, draft_text, item_id),
        )


def mark_draft_failed(item_id: int, error: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE replies SET status = 'failed', error = ? WHERE id = ?",
            (f"draft: {error[:300]}", item_id),
        )


def get_item(item_id: int) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM replies WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def mark_posted(
    item_id: int,
    reply_platform_id: str,
    reply_url: str | None = None,
    final_text: str | None = None,
) -> None:
    """Persist a successful publish: status=posted, ids/url + posted_at."""
    fields = [
        "status = 'posted'",
        "reply_platform_id = ?",
        "reply_url = ?",
        "posted_at = CURRENT_TIMESTAMP",
        "error = NULL",
    ]
    args: list[Any] = [reply_platform_id, reply_url]
    if final_text is not None:
        fields.append("final_text = ?")
        args.append(final_text)
    args.append(item_id)
    with _conn() as c:
        c.execute(f"UPDATE replies SET {', '.join(fields)} WHERE id = ?", args)


def mark_post_failed(item_id: int, error: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE replies SET status = 'failed', error = ? WHERE id = ?",
            (f"post: {error[:500]}", item_id),
        )


def has_replied(platform: str, account: str, parent_post_id: str) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM replies WHERE platform = ? AND account_username = ? "
            "AND parent_post_id = ? AND status IN ('posted', 'approved')",
            (platform, account, parent_post_id),
        ).fetchone()
    return row is not None


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
    """Insert a freshly scraped post with status='scraped'.

    Returns the inserted row id, or None if a duplicate exists for this
    (platform, account, post_id) — dedup is enforced by the UNIQUE index.
    """
    if parent_created_at is not None and hasattr(parent_created_at, "isoformat"):
        parent_created_at = parent_created_at.isoformat()

    with _conn() as c:
        try:
            cur = c.execute(
                """
                INSERT INTO replies (
                    platform, account_username, parent_post_id, parent_post_url,
                    parent_post_text, parent_author, parent_likes, parent_replies,
                    parent_created_at, status, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scraped', ?)
                """,
                (
                    platform,
                    account_username,
                    parent_post_id,
                    parent_post_url,
                    parent_post_text,
                    parent_author,
                    parent_likes,
                    parent_replies,
                    parent_created_at,
                    note,
                ),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def last_scrape_at(platform: str | None = None) -> str | None:
    """Most recent scraped_at timestamp."""
    q = "SELECT MAX(scraped_at) AS ts FROM replies"
    args: list[Any] = []
    if platform:
        q += " WHERE platform = ?"
        args.append(platform)
    with _conn() as c:
        row = c.execute(q, args).fetchone()
    return row["ts"] if row and row["ts"] else None


def queue_counts() -> dict[tuple[str, str], int]:
    with _conn() as c:
        rows = c.execute(
            "SELECT platform, status, COUNT(*) AS n FROM replies GROUP BY platform, status"
        ).fetchall()
    return {(r["platform"], r["status"]): r["n"] for r in rows}
