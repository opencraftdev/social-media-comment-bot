"""X (Twitter) scraper using Playwright + cookies.

Why not twikit: as of Nov 2025 twikit's transaction-id pipeline + response parsers
are out-of-sync with current X. Each call fails differently. Playwright with
authenticated cookies is the reliable path until twikit catches up.

Flow:
  1. Load cookies from accounts/x_<username>.cookies.json (set via `x-login` or
     `x-paste-cookies` CLI commands)
  2. Open x.com/search?q=<keyword>&f=top per brand keyword
  3. Scroll a few times to load more tweets
  4. Extract tweets via [data-testid] selectors (these are X's stable hooks)
  5. Apply brand filters
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import steel as steel_sdk

from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
)

from src.scraper.filters import passes_brand_filters
from src.scraper.threads_spider import ScrapedPost


ACCOUNTS_DIR = Path(__file__).resolve().parents[2] / "accounts"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _cookies_path(username: str) -> Path:
    return ACCOUNTS_DIR / f"x_{username}.cookies.json"


def _to_playwright_cookies(flat: dict[str, str]) -> list[dict]:
    """Convert our flat {name: value} cookie dict to Playwright's expected format."""
    out = []
    for name, value in flat.items():
        out.append({
            "name": name,
            "value": value,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": name in {"auth_token"},
            "sameSite": "Lax",
        })
    return out


_NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*([KMkm]?)")


def _parse_count(text: str | None) -> int:
    if not text:
        return 0
    m = _NUM_RE.search(text)
    if not m:
        return 0
    num = float(m.group(1).replace(",", "."))
    suf = m.group(2).upper()
    if suf == "K":
        num *= 1_000
    elif suf == "M":
        num *= 1_000_000
    return int(num)


_STATUS_URL_RE = re.compile(r"^https?://(?:www\.)?x\.com/([\w]+)/status/(\d+)")


async def _scrape_search(
    page: Page, keyword: str, per_kw: int, lang_hint: str | None = None
) -> list[ScrapedPost]:
    """Scrape one keyword's search results. lang_hint adds X's `lang:<code>` operator."""
    query = f"{keyword} lang:{lang_hint}" if lang_hint else keyword
    url = f"https://x.com/search?q={quote_plus(query)}&src=typed_query&f=top"
    posts: list[ScrapedPost] = []

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except PlaywrightTimeout:
        print(f"    [!] timeout loading search for '{keyword}'")
        return posts

    try:
        await page.wait_for_selector("article[data-testid='tweet']", timeout=15000)
    except PlaywrightTimeout:
        body = (await page.content())[:800].lower()
        if "log in" in body or "sign up" in body:
            print(f"    [!] login wall — cookies may be invalid or expired")
        else:
            print(f"    [!] no tweets rendered for '{keyword}'")
        return posts

    # Scroll a few times to load more tweets
    for _ in range(3):
        await page.mouse.wheel(0, 2400)
        await asyncio.sleep(random.uniform(1.0, 2.0))

    # Extract tweet cards
    rows = await page.evaluate(
        """() => {
            const cards = Array.from(document.querySelectorAll("article[data-testid='tweet']"));
            return cards.map(card => {
                const textEl = card.querySelector("[data-testid='tweetText']");
                const text = textEl ? (textEl.innerText || '') : '';

                // Permalink — anchor wrapping a <time>
                const tEl = card.querySelector('time');
                const timeIso = tEl ? (tEl.getAttribute('datetime') || '') : '';
                const permaAnchor = tEl ? tEl.closest('a') : null;
                const href = permaAnchor ? permaAnchor.href : '';

                // Author — User-Name testid
                const userBlock = card.querySelector("[data-testid='User-Name']");
                const userText = userBlock ? (userBlock.innerText || '') : '';
                // userText format: 'Display Name\\n@handle\\n·\\n2h'
                const handleMatch = userText.match(/@([\\w]+)/);
                const handle = handleMatch ? handleMatch[1] : '';

                // Engagement
                const reply = card.querySelector("[data-testid='reply']");
                const like = card.querySelector("[data-testid='like'], [data-testid='unlike']");
                const retweet = card.querySelector("[data-testid='retweet'], [data-testid='unretweet']");
                const view = card.querySelector("a[href*='/analytics']");

                const txt = (el) => el ? (el.textContent || '').trim() : '';

                return {
                    href, timeIso, handle, text,
                    reply: txt(reply),
                    like: txt(like),
                    retweet: txt(retweet),
                    view: txt(view),
                };
            }).filter(r => r.href && r.handle && r.text);
        }"""
    )

    seen: set[str] = set()
    for r in rows:
        m = _STATUS_URL_RE.match(r["href"])
        if not m:
            continue
        author = m.group(1)
        tid = m.group(2)
        if tid in seen:
            continue
        seen.add(tid)

        created_at = None
        if r["timeIso"]:
            try:
                created_at = datetime.fromisoformat(r["timeIso"].replace("Z", "+00:00"))
            except ValueError:
                pass

        posts.append(
            ScrapedPost(
                platform="x",
                parent_post_id=tid,
                parent_post_url=f"https://x.com/{author}/status/{tid}",
                parent_post_text=(r["text"] or "")[:1000],
                parent_author=r["handle"] or author,
                parent_likes=_parse_count(r["like"]),
                parent_replies=_parse_count(r["reply"]),
                keyword=keyword,
                created_at=created_at,
                raw={
                    "retweet": _parse_count(r["retweet"]),
                    "view": _parse_count(r["view"]),
                },
            )
        )
        if len(posts) >= per_kw:
            break

    return posts


async def scrape_x_viral(brand: dict, limit: int = 30) -> list[ScrapedPost]:
    """Run X scrape across brand keywords. Returns deduped, brand-filtered posts."""
    username = brand["accounts"]["x_twitter"]["username"]
    cookies_path = _cookies_path(username)

    if not cookies_path.exists():
        raise RuntimeError(
            f"No X cookies at {cookies_path}. "
            "Run: python -m src.cli x-paste-cookies"
        )

    with cookies_path.open() as f:
        flat_cookies = json.load(f)
    pw_cookies = _to_playwright_cookies(flat_cookies)

    keywords = brand["viral_post_filters"]["monitor_keywords"]
    id_extra = brand["viral_post_filters"].get("monitor_keywords_id_extra") or []
    per_kw_limit = max(3, limit // max(1, len(keywords)))

    # Language sweep order from brand: priority first (e.g., id then en)
    lang_pref = brand["viral_post_filters"].get("language_preference") or [None]
    if lang_pref and lang_pref[0]:
        print(f"  · language sweep order: {' → '.join(lang_pref)}")
    print(f"  · keywords per sweep: {len(keywords)} (+ {len(id_extra)} ID-extras on ID sweeps)")

    # Collect ~3x the final limit so filtering can drop many without leaving us empty.
    # First keep ID candidates; only do EN sweep if we still need more *after* filtering.
    raw_target = max(limit * 3, 30)
    all_posts: list[ScrapedPost] = []
    seen_ids: set[str] = set()
    # Track sweep label per post so we can preserve ID-priority when ranking
    sweep_index: dict[str, int] = {}

    steel_api_key = os.environ.get("STEEL_API_KEY")
    if steel_api_key:
        steel_client = steel_sdk.Steel(steel_api_key=steel_api_key)
        session = steel_client.sessions.create()
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.connect_over_cdp(session.websocket_url)
                ctx = await browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 900},
                    locale="en-US",
                )
                await ctx.add_cookies(pw_cookies)

                page = await ctx.new_page()
                try:
                    for sweep_idx, lang_hint in enumerate(lang_pref):
                        if sweep_idx > 0:
                            cooldown = random.uniform(20.0, 35.0)
                            print(f"\n  ── cooldown {cooldown:.0f}s before next sweep (avoid X throttle) ──")
                            await asyncio.sleep(cooldown)

                        tag = f"lang:{lang_hint}" if lang_hint else "(no lang filter)"
                        print(f"\n  ── sweep {sweep_idx + 1}: {tag} ──")

                        # Indonesian sweep also uses ID-extra keywords ('ai untuk developer' etc.)
                        sweep_keywords = keywords + (id_extra if lang_hint == "id" else [])

                        for kw in sweep_keywords:
                            if len(all_posts) >= raw_target:
                                break
                            print(f"  · keyword: {kw}")
                            try:
                                results = await _scrape_search(page, kw, per_kw_limit, lang_hint=lang_hint)
                            except Exception as e:
                                print(f"    [!] error: {e.__class__.__name__}: {e}")
                                results = []

                            new_this_kw = 0
                            for p in results:
                                if p.parent_post_id in seen_ids:
                                    continue
                                seen_ids.add(p.parent_post_id)
                                sweep_index[p.parent_post_id] = sweep_idx
                                all_posts.append(p)
                                new_this_kw += 1
                            if new_this_kw:
                                print(f"    + {new_this_kw} new")

                            await asyncio.sleep(random.uniform(4.0, 8.0))
                finally:
                    await ctx.close()
                    await browser.close()
        finally:
            steel_client.sessions.release(session.id)
    else:
        # Fallback: local Playwright (dev without Steel key)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            await ctx.add_cookies(pw_cookies)

            page = await ctx.new_page()
            try:
                for sweep_idx, lang_hint in enumerate(lang_pref):
                    if sweep_idx > 0:
                        cooldown = random.uniform(20.0, 35.0)
                        print(f"\n  ── cooldown {cooldown:.0f}s before next sweep (avoid X throttle) ──")
                        await asyncio.sleep(cooldown)

                    tag = f"lang:{lang_hint}" if lang_hint else "(no lang filter)"
                    print(f"\n  ── sweep {sweep_idx + 1}: {tag} ──")

                    # Indonesian sweep also uses ID-extra keywords ('ai untuk developer' etc.)
                    sweep_keywords = keywords + (id_extra if lang_hint == "id" else [])

                    for kw in sweep_keywords:
                        if len(all_posts) >= raw_target:
                            break
                        print(f"  · keyword: {kw}")
                        try:
                            results = await _scrape_search(page, kw, per_kw_limit, lang_hint=lang_hint)
                        except Exception as e:
                            print(f"    [!] error: {e.__class__.__name__}: {e}")
                            results = []

                        new_this_kw = 0
                        for p in results:
                            if p.parent_post_id in seen_ids:
                                continue
                            seen_ids.add(p.parent_post_id)
                            sweep_index[p.parent_post_id] = sweep_idx
                            all_posts.append(p)
                            new_this_kw += 1
                        if new_this_kw:
                            print(f"    + {new_this_kw} new")

                        await asyncio.sleep(random.uniform(4.0, 8.0))
            finally:
                await ctx.close()
                await browser.close()

    # Apply brand filters (self-skip + the rest)
    kept: list[ScrapedPost] = []
    drop_counts: dict[str, int] = {}
    for p in all_posts:
        ok, reason = passes_brand_filters(
            platform="x",
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

    # Sort: ID-sweep posts first (preserve language priority), then by engagement
    kept.sort(
        key=lambda p: (
            sweep_index.get(p.parent_post_id, 999),
            -(p.parent_likes + p.parent_replies * 2),
        )
    )
    return kept[:limit]
