# Firecrawl + Steel Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all local Playwright/Chromium usage with Firecrawl (Threads scraper) and Steel (X scraper, Threads poster, X poster) so the VPS runs zero local browser processes.

**Architecture:** Firecrawl handles the public Threads search scrape via API (no auth needed, no Chromium). Steel hosts a remote cloud browser for everything that needs authenticated cookie sessions (X scrape, Threads post, X post). All existing function signatures stay the same — `cli.py` needs zero changes.

**Tech Stack:** `firecrawl-py`, `steel-sdk`, `httpx`, existing `playwright` (now connects to Steel's remote CDP endpoint instead of launching locally)

---

## File Map

| File | Change |
|------|--------|
| `requirements.txt` | Add `firecrawl-py>=1.0.0`, `steel-sdk>=0.1.0` |
| `.env` | Add `FIRECRAWL_API_KEY`, `STEEL_API_KEY` |
| `src/scraper/threads_spider.py` | **Rewrite** — Firecrawl replaces Playwright |
| `src/scraper/x_spider.py` | **Modify** — Steel remote browser replaces local launch |
| `src/poster/threads_poster.py` | **Modify** — Steel remote browser replaces local launch |
| `src/poster/x_poster.py` | **Modify** — Steel remote browser replaces local launch |

`cli.py` is **not touched** — same import/call pattern throughout.

---

## Task 1: Dependencies + Env Vars

**Files:**
- Modify: `requirements.txt`
- Modify: `.env` (add keys)

- [ ] **Step 1: Add packages to requirements.txt**

```text
firecrawl-py>=1.0.0
steel-sdk>=0.1.0
```

Full updated `requirements.txt`:
```text
anthropic>=0.39.0
httpx[socks]>=0.27.0
twikit>=2.3.3
playwright>=1.48.0
python-dotenv>=1.0.0
langdetect>=1.0.9
supabase>=2.0.0
firecrawl-py>=1.0.0
steel-sdk>=0.1.0
```

- [ ] **Step 2: Install**

```bash
pip install firecrawl-py steel-sdk
```

- [ ] **Step 3: Add env vars to .env**

```bash
FIRECRAWL_API_KEY=fc-your-key-here
STEEL_API_KEY=steel-your-key-here
```

Get keys from:
- Firecrawl: https://firecrawl.dev → Dashboard → API Keys
- Steel: https://app.steel.dev → Settings → API Keys

- [ ] **Step 4: Verify imports work**

```bash
python -c "from firecrawl import FirecrawlApp; print('firecrawl ok')"
python -c "import steel; print('steel ok')"
```

Expected: both print their ok message.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt
git commit -m "chore: add firecrawl-py and steel-sdk dependencies"
```

---

## Task 2: Threads Scraper → Firecrawl

**Files:**
- Rewrite: `src/scraper/threads_spider.py`

The public API is unchanged: `scrape_threads_viral(brand, limit) -> list[ScrapedPost]`

**How it works:**
1. For each keyword, call Firecrawl `scrape_url` on the Threads search URL with `formats=['links']` to get all post permalinks
2. Deduplicate permalinks matching `/@<author>/post/<shortcode>` pattern
3. For each permalink, call Firecrawl `scrape_url` with `formats=['extract']` and a structured schema to get post text + engagement
4. Apply brand filters (same `passes_brand_filters()` call as before)

- [ ] **Step 1: Rewrite `src/scraper/threads_spider.py`**

```python
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

# Re-export ScrapedPost so cli.py imports keep working
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
    """
    Scrape Threads search page and return list of (url, author, shortcode) tuples.
    """
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
    """
    Scrape individual post page and extract text + engagement via Firecrawl extract.
    """
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


def scrape_threads_viral(brand: dict, limit: int = 30) -> list[ScrapedPost]:
    """Scrape Threads for viral posts matching brand keywords via Firecrawl."""
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
```

- [ ] **Step 2: Smoke test**

```bash
python -c "
from dotenv import load_dotenv; load_dotenv()
from src.brand.loader import load_brand_profile
from src.scraper.threads_spider import scrape_threads_viral
brand = load_brand_profile()
brand['viral_post_filters']['monitor_keywords'] = ['claude code']
posts = scrape_threads_viral(brand, limit=3)
print(f'Got {len(posts)} posts')
for p in posts:
    print(f'  @{p.parent_author}: {p.parent_post_text[:80]}')
"
```

Expected: prints 0-3 posts (may be 0 if no Indonesian posts match filters — that's fine).

- [ ] **Step 3: Commit**

```bash
git add src/scraper/threads_spider.py
git commit -m "feat: migrate Threads scraper from Playwright to Firecrawl"
```

---

## Task 3: X Scraper → Steel

**Files:**
- Modify: `src/scraper/x_spider.py`

**Change:** Replace `async_playwright()` local launch with Steel remote CDP connection. All existing scraping logic (cookie injection, `lang:id` sweep, selectors, filters) stays identical.

The public API is unchanged: `scrape_x_viral(brand, limit) -> list[ScrapedPost]`

- [ ] **Step 1: Add Steel session helper at top of `src/scraper/x_spider.py`**

Read the current file first. At the top, after existing imports, add:

```python
import steel as steel_sdk
```

Replace the `async_playwright()` context manager in `scrape_x_viral` (currently around line 195 inside the function) with a Steel session:

Find this pattern:
```python
async with async_playwright() as pw:
    browser = await pw.chromium.launch(headless=True)
```

Replace with:
```python
steel_api_key = os.environ.get("STEEL_API_KEY")
if steel_api_key:
    steel_client = steel_sdk.Steel(steel_api_key=steel_api_key)
    session = steel_client.sessions.create()
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(session.websocket_url)
            # ... rest of existing logic unchanged ...
    finally:
        steel_client.sessions.release(session.id)
else:
    # Fallback: local Playwright (dev without Steel key)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        # ... rest of existing logic unchanged ...
```

- [ ] **Step 2: Add `import os` if not already present in x_spider.py**

Check with:
```bash
grep "^import os" src/scraper/x_spider.py
```

If missing, add to imports section.

- [ ] **Step 3: Smoke test**

```bash
python -m src.cli scrapers --probe
```

Expected: connects to X session via Steel (or local Playwright fallback), reports cookie validity.

- [ ] **Step 4: Commit**

```bash
git add src/scraper/x_spider.py
git commit -m "feat: migrate X scraper from local Playwright to Steel remote browser"
```

---

## Task 4: Threads Poster → Steel

**Files:**
- Modify: `src/poster/threads_poster.py`

**Change:** Same pattern as Task 3. Replace local browser launch with Steel remote CDP. All cookie injection, DOM interaction, and verification logic stays identical.

The public API is unchanged: `post_threads_reply(item) -> dict`

- [ ] **Step 1: Add Steel import to `src/poster/threads_poster.py`**

At the top of the file, after existing imports, add:
```python
import steel as steel_sdk
```

- [ ] **Step 2: Locate and replace the browser launch in `post_threads_reply`**

In `post_threads_reply` (around line 446), find:

```python
async with async_playwright() as pw:
    ...
    browser, ctx = await _new_logged_in_context(pw, cookies)
```

Wrap with Steel:
```python
steel_api_key = os.environ.get("STEEL_API_KEY")
if steel_api_key:
    steel_client = steel_sdk.Steel(steel_api_key=steel_api_key)
    session = steel_client.sessions.create()
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(session.websocket_url)
            ctx = await _new_logged_in_context_from_browser(browser, cookies)
            # ... rest of existing logic unchanged ...
    finally:
        steel_client.sessions.release(session.id)
else:
    async with async_playwright() as pw:
        browser, ctx = await _new_logged_in_context(pw, cookies)
        # ... rest of existing logic unchanged ...
```

Note: `_new_logged_in_context` currently takes `pw` (a Playwright instance) and calls `pw.chromium.launch()` internally. When using Steel, the browser is already connected. You need to pass the connected `browser` object directly and call `browser.new_context(...)` + cookie injection on it instead of launching a new browser.

To handle this cleanly, add a helper:

```python
async def _new_logged_in_context_from_browser(browser, cookies: dict[str, str]):
    """Same as _new_logged_in_context but for an already-connected browser (Steel)."""
    ctx = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
    )
    playwright_cookies = _to_playwright_cookies_threads(cookies)
    await ctx.add_cookies(playwright_cookies)
    return ctx
```

- [ ] **Step 3: Smoke test (dry run)**

```bash
THREADS_POST_DRY_RUN=1 python -m src.cli post --id <any_approved_id>
```

Expected: navigates to post, finds reply button, then aborts before submitting. No actual post sent.

- [ ] **Step 4: Commit**

```bash
git add src/poster/threads_poster.py
git commit -m "feat: migrate Threads poster from local Playwright to Steel remote browser"
```

---

## Task 5: X Poster → Steel

**Files:**
- Modify: `src/poster/x_poster.py`

**Change:** Same Steel pattern as Tasks 3 & 4.

The public API is unchanged: `post_x_reply(item) -> dict`

- [ ] **Step 1: Add Steel import to `src/poster/x_poster.py`**

```python
import steel as steel_sdk
```

- [ ] **Step 2: Locate `post_x_reply` function and add Steel wrapper**

In `post_x_reply` (around line 145), find the `async_playwright()` context manager and wrap with Steel using the same pattern as Task 4:

```python
steel_api_key = os.environ.get("STEEL_API_KEY")
if steel_api_key:
    steel_client = steel_sdk.Steel(steel_api_key=steel_api_key)
    session = steel_client.sessions.create()
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(session.websocket_url)
            browser_ctx, ctx = await _new_logged_in_context_from_browser(browser, cookies)
            # ... rest of existing logic unchanged ...
    finally:
        steel_client.sessions.release(session.id)
else:
    async with async_playwright() as pw:
        browser_ctx, ctx = await _new_logged_in_context(pw, cookies)
        # ... rest of existing logic unchanged ...
```

Add the same `_new_logged_in_context_from_browser` helper as in Task 4 (adapted for x_poster cookie format).

- [ ] **Step 3: Smoke test**

```bash
python -m src.cli x-test
```

Expected: verifies X cookies work (now via Steel remote browser).

- [ ] **Step 4: Commit**

```bash
git add src/poster/x_poster.py
git commit -m "feat: migrate X poster from local Playwright to Steel remote browser"
```

---

## Task 6: Verify Full Flow

- [ ] **Step 1: Restart daemon**

```bash
python -m src.cli daemon --interval 15
```

- [ ] **Step 2: Trigger scrape from web UI**

Trigger scrape for both platforms. Check logs for:
- Threads: `Firecrawl` calls (no Chromium launch messages)
- X: Steel session creation log

- [ ] **Step 3: Confirm zero local Chromium processes**

```bash
ps aux | grep -i chrom
```

Expected: no `chrome-headless-shell` or `chromium` processes.

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "feat: complete Firecrawl + Steel migration — zero local Chromium"
```

---

## Fallback Notes

- If `FIRECRAWL_API_KEY` is not set → `scrape_threads_viral` raises `RuntimeError` immediately (explicit failure, not silent)
- If `STEEL_API_KEY` is not set → all Steel-wrapped functions fall back to local Playwright (safe for local dev)
- Playwright remains in `requirements.txt` as a dependency (needed for Steel CDP connection + fallback)
