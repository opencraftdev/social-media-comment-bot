"""Threads scraper using Playwright + Steel remote browser.

Firecrawl does not support threads.net, so we use Steel (cloud CDP) with the
same Playwright-based scraping logic as before. Falls back to local Playwright
if STEEL_API_KEY is not set (for local dev without Steel credentials).

Strategy:
  1. Per keyword: open Threads search page, collect post permalinks
  2. Hydrate each post: open post page, extract text + engagement
  3. Apply brand filters and return keepers

Env vars:
  STEEL_API_KEY — optional; if unset, local Playwright is used instead
"""
from __future__ import annotations

import asyncio
import os
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

import steel as steel_sdk
from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
)

from src.scraper.filters import passes_brand_filters


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


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


_REL_TIME_RE = re.compile(r"(\d+)\s*([smhdwy])", re.I)


def _parse_relative_time(s: str) -> datetime | None:
    if not s:
        return None
    m = _REL_TIME_RE.search(s)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    seconds = {
        "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31536000
    }.get(unit, 0)
    if not seconds:
        return None
    return datetime.now(timezone.utc) - timedelta(seconds=n * seconds)


_THREADS_URL_RE = re.compile(
    r"^https?://(?:www\.)?threads\.(?:net|com)/@([\w.]+)/post/([\w-]+)"
)

_SHORTCODE_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


def shortcode_to_id(shortcode: str) -> str:
    post_id = 0
    for ch in shortcode:
        post_id = post_id * 64 + _SHORTCODE_ALPHABET.index(ch)
    return str(post_id)


def parse_threads_url(url: str) -> dict | None:
    m = _THREADS_URL_RE.match(url)
    if not m:
        return None
    username, shortcode = m.groups()
    try:
        pid = shortcode_to_id(shortcode)
    except ValueError:
        pid = shortcode
    return {
        "username": username,
        "shortcode": shortcode,
        "post_id": pid,
        "url": url.split("?")[0],
    }


_COUNT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*([KMkm]?)")


def _parse_count(text: str | None) -> int:
    if not text:
        return 0
    m = _COUNT_RE.search(text)
    if not m:
        return 0
    num = float(m.group(1).replace(",", "."))
    suffix = m.group(2).upper()
    if suffix == "K":
        num *= 1_000
    elif suffix == "M":
        num *= 1_000_000
    return int(num)


async def _setup_context(browser: Browser) -> BrowserContext:
    return await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        device_scale_factor=2,
    )


async def _hydrate_post(ctx: BrowserContext, post: ScrapedPost) -> None:
    """Open the post page and extract text + engagement from rendered DOM."""
    page = await ctx.new_page()
    try:
        await page.goto(post.parent_post_url, wait_until="domcontentloaded", timeout=20000)
        try:
            await page.wait_for_selector("article, [data-pressable-container]", timeout=12000)
        except PlaywrightTimeout:
            return

        try:
            data = await page.evaluate(
                """() => {
                    const root = document.querySelector('article')
                              || document.querySelector('[data-pressable-container]');
                    if (!root) return null;
                    const t = root.querySelector('time');
                    return {
                        text: (root.innerText || '').slice(0, 3000),
                        time_iso: t ? (t.getAttribute('datetime') || '') : '',
                        time_text: t ? (t.textContent || '') : ''
                    };
                }"""
            )
        except Exception:
            data = None

        if not data:
            return

        text_blob = data.get("text") or ""
        if not text_blob:
            return

        iso = (data.get("time_iso") or "").strip()
        if iso:
            try:
                post.created_at = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            except ValueError:
                pass
        if not post.created_at:
            rel = _parse_relative_time(data.get("time_text") or "")
            if rel:
                post.created_at = rel

        lines = [ln.strip() for ln in text_blob.split("\n") if ln.strip()]
        body_lines: list[str] = []
        trailing_nums: list[str] = []

        _BARE_NUM_RE = re.compile(r"^[\d]+(?:[.,]\d+)?\s*[KMkm]?$")
        _TIME_LINE_RE = re.compile(
            r"^(?:\d+\s*[smhdy]|\d{1,2}/\d{1,2}/\d{2,4}|just now|edited|translate)$", re.I
        )

        for ln in lines:
            if ln.lower() == post.parent_author.lower():
                continue
            if _TIME_LINE_RE.match(ln):
                continue
            if _BARE_NUM_RE.match(ln):
                trailing_nums.append(ln)
                continue
            if trailing_nums:
                break
            body_lines.append(ln)

        body = "\n".join(body_lines).strip()[:1000]
        if body:
            post.parent_post_text = body

        if len(trailing_nums) >= 1:
            post.parent_likes = _parse_count(trailing_nums[0])
        if len(trailing_nums) >= 2:
            post.parent_replies = _parse_count(trailing_nums[1])
        post.raw["engagement_raw"] = trailing_nums[:4]

    except Exception as e:
        print(f"    [!] hydrate error for {post.parent_post_url}: {e.__class__.__name__}: {e}")
    finally:
        await page.close()


async def _scrape_one_keyword(page: Page, keyword: str, limit: int) -> list[ScrapedPost]:
    """Scrape Threads search results for a single keyword."""
    url = f"https://www.threads.net/search?q={quote_plus(keyword)}&serp_type=default&filter=top"
    posts: list[ScrapedPost] = []

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except PlaywrightTimeout:
        print(f"  [!] timeout loading search for '{keyword}'")
        return posts

    try:
        await page.wait_for_selector("a[href*='/@'][href*='/post/']", timeout=12000)
    except PlaywrightTimeout:
        body_text = (await page.content())[:600].lower()
        if "log in" in body_text or "sign up" in body_text:
            print(f"  [!] login wall for '{keyword}' — skipping")
        else:
            print(f"  [!] no post links rendered for '{keyword}'")
        return posts

    for _ in range(3):
        await page.mouse.wheel(0, 1800)
        await asyncio.sleep(random.uniform(0.8, 1.6))

    hrefs = await page.evaluate(
        """() => Array.from(document.querySelectorAll("a[href*='/post/']"))
                .map(a => a.href)
                .filter(h => /\\/@[^/]+\\/post\\//.test(h))
        """
    )
    seen: set[str] = set()
    permalinks: list[str] = []
    for h in hrefs:
        clean = h.split("?")[0]
        if clean not in seen:
            seen.add(clean)
            permalinks.append(clean)

    for permalink in permalinks[:limit]:
        parsed = parse_threads_url(permalink)
        if not parsed:
            continue

        try:
            card_data = await page.evaluate(
                """(href) => {
                    const anchor = document.querySelector(`a[href^='${href}']`);
                    if (!anchor) return null;
                    let el = anchor;
                    while (el && el.tagName !== 'ARTICLE' && el.parentElement) {
                        el = el.parentElement;
                    }
                    const root = el || anchor.closest('div');
                    if (!root) return null;
                    const text = root.innerText || '';
                    const m = text.match(/([\\d,.]+\\s*[KMkm]?)\\s*likes?/i);
                    const r = text.match(/([\\d,.]+\\s*[KMkm]?)\\s*repl(?:y|ies)/i);
                    return {
                        text: text,
                        likes_raw: m ? m[1] : null,
                        replies_raw: r ? r[1] : null,
                    };
                }""",
                permalink,
            )
        except Exception:
            card_data = None

        text = ""
        likes = 0
        replies = 0
        if card_data:
            text = (card_data.get("text") or "").strip()[:1000]
            likes = _parse_count(card_data.get("likes_raw"))
            replies = _parse_count(card_data.get("replies_raw"))

        posts.append(
            ScrapedPost(
                platform="threads",
                parent_post_id=parsed["post_id"],
                parent_post_url=parsed["url"],
                parent_post_text=text,
                parent_author=parsed["username"],
                parent_likes=likes,
                parent_replies=replies,
                keyword=keyword,
                raw={"shortcode": parsed["shortcode"]},
            )
        )

    return posts


async def _run_with_browser(browser: Browser, brand: dict, limit: int) -> list[ScrapedPost]:
    """Core scraping logic shared by Steel and local Playwright paths."""
    keywords = brand["viral_post_filters"]["monitor_keywords"]
    per_kw_limit = max(3, limit // max(1, len(keywords)))

    all_posts: list[ScrapedPost] = []
    seen_ids: set[str] = set()

    ctx = await _setup_context(browser)
    page = await ctx.new_page()
    try:
        for kw in keywords:
            print(f"  · keyword: {kw}")
            results = await _scrape_one_keyword(page, kw, per_kw_limit)

            for p in results:
                if p.parent_post_id in seen_ids:
                    continue
                seen_ids.add(p.parent_post_id)
                all_posts.append(p)

            await asyncio.sleep(random.uniform(2.0, 4.0))

            if len(all_posts) >= limit:
                break
    finally:
        await ctx.close()

    # Hydrate: open each post page to extract full text + timestamps
    if all_posts:
        print(f"  · hydrating {len(all_posts)} posts…")
        async with async_playwright() as pw2:
            if os.environ.get("STEEL_API_KEY"):
                hydrate_api_key = os.environ["STEEL_API_KEY"]
                steel_client = steel_sdk.Steel(steel_api_key=hydrate_api_key)
                session = steel_client.sessions.create()
                try:
                    b2 = await pw2.chromium.connect_over_cdp(
                        f"wss://connect.steel.dev?apiKey={hydrate_api_key}&sessionId={session.id}"
                    )
                    ctx2 = await _setup_context(b2)
                    try:
                        sem = asyncio.Semaphore(2)

                        async def _bound(p: ScrapedPost) -> None:
                            async with sem:
                                await _hydrate_post(ctx2, p)

                        await asyncio.gather(*(_bound(p) for p in all_posts))
                    finally:
                        await ctx2.close()
                        await b2.close()
                finally:
                    steel_client.sessions.release(session.id)
            else:
                b2 = await pw2.chromium.launch(headless=True)
                ctx2 = await _setup_context(b2)
                try:
                    sem = asyncio.Semaphore(2)

                    async def _bound(p: ScrapedPost) -> None:
                        async with sem:
                            await _hydrate_post(ctx2, p)

                    await asyncio.gather(*(_bound(p) for p in all_posts))
                finally:
                    await ctx2.close()
                    await b2.close()

    return all_posts


async def scrape_threads_viral(brand: dict, limit: int = 30) -> list[ScrapedPost]:
    """Scrape Threads for viral posts matching brand keywords.

    Uses Steel remote browser if STEEL_API_KEY is set, otherwise falls back
    to local Playwright (for dev without Steel credentials).
    """
    steel_api_key = os.environ.get("STEEL_API_KEY")

    if steel_api_key:
        steel_client = steel_sdk.Steel(steel_api_key=steel_api_key)
        session = steel_client.sessions.create()
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.connect_over_cdp(
                    f"wss://connect.steel.dev?apiKey={steel_api_key}&sessionId={session.id}"
                )
                all_posts = await _run_with_browser(browser, brand, limit)
                await browser.close()
        finally:
            steel_client.sessions.release(session.id)
    else:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            all_posts = await _run_with_browser(browser, brand, limit)
            await browser.close()

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
