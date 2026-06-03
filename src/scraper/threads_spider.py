"""Threads scraper using Firecrawl API.

Replaces the Playwright-based scraper. No local Chromium needed.
Firecrawl handles JS rendering on their infrastructure.

Strategy:
  1. For each keyword, scrape Threads search page → extract post links
  2. For each post link, scrape post page → extract text + engagement
  3. Apply brand filters and return keepers

Env vars:
  FIRECRAWL_API_KEY — required
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from firecrawl import FirecrawlApp

from src.scraper.filters import passes_brand_filters


@dataclass
class ScrapedPost:
    platform: str
    parent_post_id: str
    parent_post_url: str
    parent_post_text: str
    parent_author: str
    parent_likes: int = 0
    parent_replies: int = 0
    keyword: str = ""
    created_at: datetime | None = None
    raw: dict = field(default_factory=dict)


_THREADS_POST_RE = re.compile(
    r"https?://(?:www\.)?threads\.(?:net|com)/@([\w.]+)/post/([\w-]+)"
)

_SHORTCODE_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)

_COUNT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*([KMkm]?)")


def _shortcode_to_id(shortcode: str) -> str:
    post_id = 0
    for ch in shortcode:
        post_id = post_id * 64 + _SHORTCODE_ALPHABET.index(ch)
    return str(post_id)


def _parse_count(text: str | None) -> int:
    if not text:
        return 0
    m = _COUNT_RE.search(str(text))
    if not m:
        return 0
    num = float(m.group(1).replace(",", "."))
    suffix = m.group(2).upper()
    if suffix == "K":
        num *= 1_000
    elif suffix == "M":
        num *= 1_000_000
    return int(num)


def _get_post_links(app: FirecrawlApp, keyword: str, limit: int) -> list[tuple[str, str, str]]:
    """Scrape Threads search page and return list of (url, author, shortcode) tuples."""
    from urllib.parse import quote_plus
    search_url = f"https://www.threads.net/search?q={quote_plus(keyword)}&serp_type=default&filter=top"

    try:
        result = app.scrape_url(search_url, formats=["links"])
    except Exception as e:
        print(f"  [!] Firecrawl error for keyword '{keyword}': {e}")
        return []

    links = result.links or []
    seen: set[str] = set()
    posts: list[tuple[str, str, str]] = []

    for link in links:
        url = link if isinstance(link, str) else link.get("url", "")
        m = _THREADS_POST_RE.match(url.split("?")[0])
        if not m:
            continue
        author, shortcode = m.groups()
        clean_url = f"https://www.threads.net/@{author}/post/{shortcode}"
        if clean_url in seen:
            continue
        seen.add(clean_url)
        posts.append((clean_url, author, shortcode))
        if len(posts) >= limit:
            break

    return posts


def _hydrate_post(app: FirecrawlApp, url: str, author: str, shortcode: str, keyword: str) -> ScrapedPost | None:
    """Scrape individual post page and extract text + engagement via Firecrawl extract."""
    try:
        result = app.scrape_url(
            url,
            formats=["extract"],
            extract={
                "prompt": (
                    "Extract from this Threads post page: "
                    "the main post text (full content, not truncated), "
                    "the number of likes (integer), "
                    "the number of replies (integer), "
                    "and the post published datetime in ISO 8601 format if visible. "
                    "Return null for any field not found."
                ),
                "schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "likes": {"type": "integer"},
                        "replies": {"type": "integer"},
                        "published_at": {"type": "string"},
                    },
                },
            },
        )
    except Exception as e:
        print(f"  [!] Firecrawl hydrate error for {url}: {e}")
        return None

    data = result.extract or {}
    text = (data.get("text") or "").strip()[:1000]
    likes = int(data.get("likes") or 0)
    replies = int(data.get("replies") or 0)

    created_at: datetime | None = None
    pub = data.get("published_at")
    if pub:
        try:
            created_at = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
        except ValueError:
            pass

    try:
        post_id = _shortcode_to_id(shortcode)
    except (ValueError, IndexError):
        post_id = shortcode

    return ScrapedPost(
        platform="threads",
        parent_post_id=post_id,
        parent_post_url=url,
        parent_post_text=text,
        parent_author=author,
        parent_likes=likes,
        parent_replies=replies,
        keyword=keyword,
        created_at=created_at,
        raw={"shortcode": shortcode},
    )


def _scrape_threads_viral_sync(brand: dict, limit: int = 30) -> list[ScrapedPost]:
    """Synchronous implementation of Threads scraping via Firecrawl."""
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise RuntimeError("FIRECRAWL_API_KEY not set in environment")

    app = FirecrawlApp(api_key=api_key)
    keywords = brand["viral_post_filters"]["monitor_keywords"]
    per_kw_limit = max(3, limit // max(1, len(keywords)))

    all_posts: list[ScrapedPost] = []
    seen_ids: set[str] = set()

    for kw in keywords:
        print(f"  · keyword: {kw}")
        links = _get_post_links(app, kw, per_kw_limit)

        for url, author, shortcode in links:
            try:
                post_id = str(_shortcode_to_id(shortcode))
            except (ValueError, IndexError):
                post_id = shortcode

            if post_id in seen_ids:
                continue
            seen_ids.add(post_id)

            post = _hydrate_post(app, url, author, shortcode, kw)
            if post:
                all_posts.append(post)

        if len(all_posts) >= limit:
            break

    # Apply brand filters
    kept: list[ScrapedPost] = []
    drop_counts: dict[str, int] = {}

    for p in all_posts:
        ok, reason = passes_brand_filters(
            platform="threads",
            text=p.parent_post_text,
            likes=p.parent_likes,
            replies=p.parent_replies,
            created_at=p.created_at,
            brand=brand,
            author=p.parent_author,
        )
        if ok:
            kept.append(p)
        else:
            drop_counts[reason or "unknown"] = drop_counts.get(reason or "unknown", 0) + 1

    if drop_counts:
        summary = ", ".join(f"{k}={v}" for k, v in sorted(drop_counts.items()))
        print(f"  · filter drops: {summary}")

    print(f"  → kept {len(kept)} after filters")
    return kept[:limit]


async def scrape_threads_viral(brand: dict, limit: int = 30) -> list[ScrapedPost]:
    """Scrape Threads for viral posts matching brand keywords via Firecrawl.

    Async wrapper kept for cli.py compatibility (cli.py calls asyncio.run on this).
    Actual work is synchronous — Firecrawl SDK is blocking.
    """
    return _scrape_threads_viral_sync(brand, limit)
