"""Posts replies to X via Playwright + saved cookies.

We do NOT use twikit for posting — its transaction-id pipeline + parsers are
broken against current X. Authenticated Playwright on the real DOM is the
reliable path.

Flow:
  1. Launch headless chromium, inject cookies from accounts/x_<username>.cookies.json
  2. Navigate to https://x.com/{parent_author}/status/{parent_post_id}
  3. Click the FIRST article's reply button (the parent tweet, not a thread reply)
  4. Type the reply text into the contenteditable composer (page.keyboard.type)
  5. Submit via [data-testid='tweetButton']
  6. Resolve the new reply URL by:
     a. preferred: capturing the `CreateTweet` GraphQL response and parsing rest_id
     b. fallback: navigating to our own profile and grabbing the latest status URL

Returns:
    { "reply_platform_id": "<tweet_id>", "reply_url": "https://x.com/<user>/status/<id>" }

Raises RuntimeError on any failure path.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import steel as steel_sdk

from playwright.async_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

from src.brand.loader import load_brand_profile
from src.scraper.x_spider import _to_playwright_cookies

ACCOUNTS_DIR = Path(__file__).resolve().parents[2] / "accounts"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_STATUS_URL_RE = re.compile(r"https?://(?:x|twitter)\.com/[^/]+/status/(\d+)")


def _cookies_path(username: str) -> Path:
    return ACCOUNTS_DIR / f"x_{username}.cookies.json"


def _build_tweet_url(parent_author: str | None, parent_post_id: str) -> str:
    author = (parent_author or "i").lstrip("@") or "i"
    # x.com routes /i/status/<id> to the canonical tweet page regardless of author.
    return f"https://x.com/{author}/status/{parent_post_id}"


async def _new_logged_in_context(pw, cookies: dict[str, str]) -> tuple[Any, BrowserContext]:
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
    )
    await ctx.add_cookies(_to_playwright_cookies(cookies))
    return browser, ctx


async def _new_logged_in_context_from_browser(browser, cookies: dict[str, str]):
    """Same as _new_logged_in_context but for an already-connected browser (Steel)."""
    ctx = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 900},
        locale="en-US",
    )
    playwright_cookies = _to_playwright_cookies(cookies)
    await ctx.add_cookies(playwright_cookies)
    return ctx


async def _grab_create_tweet_id(page: Page, click_submit) -> str | None:
    """Click submit while watching network for CreateTweet response. Returns rest_id or None."""
    try:
        async with page.expect_response(
            lambda r: "CreateTweet" in r.url and r.request.method == "POST",
            timeout=20000,
        ) as resp_info:
            await click_submit()
        resp = await resp_info.value
        try:
            data = await resp.json()
        except Exception:
            return None
        # Path varies but rest_id sits under data.create_tweet.tweet_results.result.rest_id
        try:
            return str(
                data["data"]["create_tweet"]["tweet_results"]["result"]["rest_id"]
            )
        except (KeyError, TypeError):
            # Walk the structure as a last-ditch
            return _find_rest_id(data)
    except PlaywrightTimeout:
        # Submit may have happened but no CreateTweet response captured
        return None


def _find_rest_id(node: Any) -> str | None:
    if isinstance(node, dict):
        if "rest_id" in node and isinstance(node["rest_id"], (str, int)):
            return str(node["rest_id"])
        for v in node.values():
            r = _find_rest_id(v)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_rest_id(v)
            if r:
                return r
    return None


async def _fallback_latest_status(page: Page, username: str) -> str | None:
    """Visit our own profile and grab the most recent status URL (id-only)."""
    try:
        await page.goto(
            f"https://x.com/{username}",
            wait_until="domcontentloaded",
            timeout=20000,
        )
        # Wait briefly for the timeline to render
        await page.wait_for_selector(
            "article[data-testid='tweet'] a[href*='/status/']", timeout=15000
        )
        href = await page.evaluate(
            """() => {
                const links = document.querySelectorAll(
                    "article[data-testid='tweet'] a[href*='/status/']"
                );
                for (const a of links) {
                    const m = a.getAttribute('href').match(/^\\/[^/]+\\/status\\/(\\d+)/);
                    if (m) return a.getAttribute('href');
                }
                return null;
            }"""
        )
        if not href:
            return None
        m = re.search(r"/status/(\d+)", href)
        return m.group(1) if m else None
    except Exception:
        return None


async def post_x_reply(item: dict[str, Any]) -> dict[str, str]:
    """Publish a reply to X.

    Args:
        item: queue row dict — must contain `parent_post_id` (and ideally
              `parent_author` for a clean URL). Uses `final_text` or `draft_text`.

    Returns:
        { "reply_platform_id": "<tweet_id>", "reply_url": "https://x.com/<user>/status/<id>" }

    Raises:
        RuntimeError on any error.
    """
    text = item.get("final_text") or item.get("draft_text")
    parent_id = item.get("parent_post_id")
    parent_author = item.get("parent_author")
    if not text:
        raise RuntimeError(f"item #{item.get('id')} has no draft_text/final_text")
    if not parent_id:
        raise RuntimeError(f"item #{item.get('id')} has no parent_post_id")

    brand = load_brand_profile()
    our_username = brand["accounts"]["x_twitter"]["username"]
    cookies_path = _cookies_path(our_username)
    if not cookies_path.exists():
        raise RuntimeError(
            f"X cookies missing at {cookies_path}. Run `python -m src.cli x-login`."
        )

    with cookies_path.open() as f:
        cookies = json.load(f)
    if not {"auth_token", "ct0"}.issubset(cookies.keys()):
        raise RuntimeError(
            "X cookies missing required keys (auth_token, ct0). Re-run x-login."
        )

    tweet_url = _build_tweet_url(parent_author, str(parent_id))

    steel_api_key = os.environ.get("STEEL_API_KEY")
    if steel_api_key:
        steel_client = steel_sdk.Steel(steel_api_key=steel_api_key)
        session = steel_client.sessions.create()
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.connect_over_cdp(session.websocket_url)
                ctx = await _new_logged_in_context_from_browser(browser, cookies)
                try:
                    page = await ctx.new_page()

                    # 1. Open the parent tweet
                    await page.goto(tweet_url, wait_until="domcontentloaded", timeout=30000)
                    if "/flow/login" in page.url or page.url.endswith("/login"):
                        raise RuntimeError(
                            f"X session expired (redirected to {page.url}). Re-run x-login."
                        )

                    try:
                        await page.wait_for_selector(
                            "article[data-testid='tweet']", timeout=20000
                        )
                    except PlaywrightTimeout:
                        raise RuntimeError(
                            f"Parent tweet did not render at {tweet_url} (404/protected/deleted?)"
                        )

                    # 2. Click reply on the FIRST article (the parent, not a thread reply)
                    first_article = page.locator("article[data-testid='tweet']").first
                    reply_btn = first_article.locator("button[data-testid='reply']")
                    try:
                        await reply_btn.wait_for(state="visible", timeout=10000)
                        await reply_btn.click()
                    except PlaywrightTimeout:
                        raise RuntimeError(
                            "Reply button not found on parent tweet — selector may have changed."
                        )

                    # 3. Focus composer (contenteditable) and type the text
                    # Try both standard and DraftJS/Lexical composer selectors
                    composer = None
                    for sel in ["[data-testid='tweetTextarea_0']", "[data-testid='tweetTextarea_0RichTextInputContainer']", "[role='textbox']"]:
                        try:
                            c = page.locator(sel).first
                            await c.wait_for(state="visible", timeout=5000)
                            composer = c
                            break
                        except PlaywrightTimeout:
                            continue
                    if composer is None:
                        await page.screenshot(path="/tmp/x-post-debug-composer.png", full_page=False)
                        raise RuntimeError("Reply composer didn't open. Screenshot saved to /tmp/x-post-debug-composer.png")
                    await composer.click()

                    # contenteditable needs keyboard.type, not fill
                    await page.keyboard.type(text, delay=15)

                    # 4. Submit — try both modal and inline submit button selectors
                    # X uses 'tweetButton' in modal replies and 'tweetButtonInline' in inline replies
                    submit_btn = None
                    for selector in [
                        "button[data-testid='tweetButton']",
                        "button[data-testid='tweetButtonInline']",
                    ]:
                        try:
                            btn = page.locator(selector)
                            await btn.wait_for(state="visible", timeout=5000)
                            submit_btn = btn
                            break
                        except PlaywrightTimeout:
                            continue
                    if submit_btn is None:
                        # Take a debug screenshot before raising
                        await page.screenshot(path="/tmp/x-post-debug-submit.png", full_page=False)
                        raise RuntimeError(
                            "Tweet submit button never appeared. "
                            "Screenshot saved to /tmp/x-post-debug-submit.png"
                        )

                    # 5. Capture CreateTweet network response while clicking
                    rest_id = await _grab_create_tweet_id(page, lambda: submit_btn.click())

                    # If we missed the network capture, give X a moment to process then fall back
                    if not rest_id:
                        await asyncio.sleep(3.0)
                        rest_id = await _fallback_latest_status(page, our_username)

                    if not rest_id:
                        raise RuntimeError(
                            "Tweet submitted but could not resolve the new tweet id."
                        )

                    reply_url = f"https://x.com/{our_username}/status/{rest_id}"
                    return {"reply_platform_id": rest_id, "reply_url": reply_url}
                finally:
                    await ctx.close()
        finally:
            steel_client.sessions.release(session.id)
    else:
        async with async_playwright() as pw:
            browser, ctx = await _new_logged_in_context(pw, cookies)
            try:
                page = await ctx.new_page()

                # 1. Open the parent tweet
                await page.goto(tweet_url, wait_until="domcontentloaded", timeout=30000)
                if "/flow/login" in page.url or page.url.endswith("/login"):
                    raise RuntimeError(
                        f"X session expired (redirected to {page.url}). Re-run x-login."
                    )

                try:
                    await page.wait_for_selector(
                        "article[data-testid='tweet']", timeout=20000
                    )
                except PlaywrightTimeout:
                    raise RuntimeError(
                        f"Parent tweet did not render at {tweet_url} (404/protected/deleted?)"
                    )

                # 2. Click reply on the FIRST article (the parent, not a thread reply)
                first_article = page.locator("article[data-testid='tweet']").first
                reply_btn = first_article.locator("button[data-testid='reply']")
                try:
                    await reply_btn.wait_for(state="visible", timeout=10000)
                    await reply_btn.click()
                except PlaywrightTimeout:
                    raise RuntimeError(
                        "Reply button not found on parent tweet — selector may have changed."
                    )

                # 3. Focus composer (contenteditable) and type the text
                # Try both standard and DraftJS/Lexical composer selectors
                composer = None
                for sel in ["[data-testid='tweetTextarea_0']", "[data-testid='tweetTextarea_0RichTextInputContainer']", "[role='textbox']"]:
                    try:
                        c = page.locator(sel).first
                        await c.wait_for(state="visible", timeout=5000)
                        composer = c
                        break
                    except PlaywrightTimeout:
                        continue
                if composer is None:
                    await page.screenshot(path="/tmp/x-post-debug-composer.png", full_page=False)
                    raise RuntimeError("Reply composer didn't open. Screenshot saved to /tmp/x-post-debug-composer.png")
                await composer.click()

                # contenteditable needs keyboard.type, not fill
                await page.keyboard.type(text, delay=15)

                # 4. Submit — try both modal and inline submit button selectors
                # X uses 'tweetButton' in modal replies and 'tweetButtonInline' in inline replies
                submit_btn = None
                for selector in [
                    "button[data-testid='tweetButton']",
                    "button[data-testid='tweetButtonInline']",
                ]:
                    try:
                        btn = page.locator(selector)
                        await btn.wait_for(state="visible", timeout=5000)
                        submit_btn = btn
                        break
                    except PlaywrightTimeout:
                        continue
                if submit_btn is None:
                    # Take a debug screenshot before raising
                    await page.screenshot(path="/tmp/x-post-debug-submit.png", full_page=False)
                    raise RuntimeError(
                        "Tweet submit button never appeared. "
                        "Screenshot saved to /tmp/x-post-debug-submit.png"
                    )

                # 5. Capture CreateTweet network response while clicking
                rest_id = await _grab_create_tweet_id(page, lambda: submit_btn.click())

                # If we missed the network capture, give X a moment to process then fall back
                if not rest_id:
                    await asyncio.sleep(3.0)
                    rest_id = await _fallback_latest_status(page, our_username)

                if not rest_id:
                    raise RuntimeError(
                        "Tweet submitted but could not resolve the new tweet id."
                    )

                reply_url = f"https://x.com/{our_username}/status/{rest_id}"
                return {"reply_platform_id": rest_id, "reply_url": reply_url}
            finally:
                await ctx.close()
                await browser.close()
