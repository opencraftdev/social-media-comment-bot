"""Posts replies to Threads via Playwright + saved cookies.

Why not the Graph API: as of 2026 Threads' Graph API requires the
`threads_keyword_search` permission (Meta App Review) before third-party apps
can reply to posts they didn't author. Until that review clears, we drive the
real web UI with authenticated cookies — same pattern as `x_poster.py`.

Flow:
  1. Launch chromium (headless unless THREADS_POST_HEADLESS=0), inject cookies
     from accounts/threads_<username>.cookies.json
  2. Navigate to item['parent_post_url'] (normalize threads.com → threads.net)
  3. Click the inline reply button on the FIRST article (parent post)
  4. Type into the contenteditable lexical editor
  5. Submit via the Post button (wait until enabled)
  6. VERIFY by re-visiting the parent post and looking for our profile link
     in the rendered DOM — only then do we mark success. No stale-profile
     fallback is treated as proof.

Env vars:
  THREADS_POST_HEADLESS = "0"  → launch with headless=False (default headless)
  THREADS_POST_DRY_RUN  = "1"  → abort right before clicking Post (for debug)
  THREADS_POST_SLOWMO   = int  → ms per Playwright action (debug)

Returns:
    { "reply_platform_id": "<shortcode_or_pk>",
      "reply_url": "https://www.threads.net/@<user>/post/<code>" }

Raises RuntimeError on any failure path. Never returns a "success" without
DOM-level proof that the reply is visible on the parent post.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from playwright.async_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

from src.brand.loader import load_brand_profile

ACCOUNTS_DIR = Path(__file__).resolve().parents[2] / "accounts"
DEBUG_DIR = Path("/tmp")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Threads post permalinks: /@author/post/<shortcode>
_POST_URL_RE = re.compile(
    r"https?://(?:www\.)?threads\.(?:net|com)/@([^/]+)/post/([A-Za-z0-9_-]+)"
)
_SHORTCODE_RE = re.compile(r"/post/([A-Za-z0-9_-]+)")


# ──────────────────────────────────────────────────────────────────────────
# Instrumentation helpers
# ──────────────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    """Step logger — prints with [threads-poster] prefix and flushes immediately."""
    print(f"[threads-poster] {msg}", flush=True)


async def _shot(page: Page, step: str) -> Path:
    """Snapshot the page to /tmp/threads-post-debug-<step>.png and log the path."""
    path = DEBUG_DIR / f"threads-post-debug-{step}.png"
    try:
        await page.screenshot(path=str(path), full_page=False)
        _log(f"screenshot saved: {path}")
    except Exception as e:
        _log(f"screenshot failed at step={step}: {e}")
    return path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_headless() -> bool:
    """THREADS_POST_HEADLESS=0 → visible. Default headless."""
    raw = os.environ.get("THREADS_POST_HEADLESS")
    if raw is None:
        return True
    return raw.strip() != "0"


# ──────────────────────────────────────────────────────────────────────────
# Cookies / context bootstrap
# ──────────────────────────────────────────────────────────────────────────

def _cookies_path(username: str) -> Path:
    return ACCOUNTS_DIR / f"threads_{username}.cookies.json"


def _to_playwright_cookies_threads(flat: dict[str, str]) -> list[dict]:
    """Mirror cookies across .threads.net / .instagram.com / .threads.com."""
    out: list[dict] = []
    for name, value in flat.items():
        for domain in (".threads.net", ".instagram.com", ".threads.com"):
            out.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "secure": True,
                "httpOnly": name in {"sessionid"},
                "sameSite": "Lax",
            })
    return out


def _normalize_threads_url(url: str) -> str:
    if not url:
        return url
    return url.replace("https://www.threads.com/", "https://www.threads.net/").replace(
        "https://threads.com/", "https://www.threads.net/"
    )


async def _new_logged_in_context(pw, cookies: dict[str, str]) -> tuple[Any, BrowserContext]:
    headless = _env_headless()
    slowmo_raw = os.environ.get("THREADS_POST_SLOWMO", "").strip()
    slowmo = int(slowmo_raw) if slowmo_raw.isdigit() else 0
    _log(f"launching chromium headless={headless} slowmo={slowmo}ms")
    browser = await pw.chromium.launch(
        headless=headless,
        slow_mo=slowmo,
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
    )
    await ctx.add_cookies(_to_playwright_cookies_threads(cookies))
    return browser, ctx


# ──────────────────────────────────────────────────────────────────────────
# UI steps
# ──────────────────────────────────────────────────────────────────────────

async def _first_post_container(page: Page):
    """Return a locator scoped to the FIRST post on the page.

    Threads' DOM varies — sometimes `<article>` exists, sometimes only
    `[data-pressable-container]` divs do. We prefer article, fall back to
    pressable-container, then to a coarse `main` scope.
    """
    candidates = ("article", "[data-pressable-container]", "main")
    for sel in candidates:
        loc = page.locator(sel).first
        try:
            await loc.wait_for(state="visible", timeout=4000)
            _log(f"first-post scope = {sel}")
            return loc, sel
        except Exception:
            continue
    raise RuntimeError(
        "no parent post container found (article / data-pressable-container / main)"
    )


async def _click_reply_button(page: Page) -> str:
    """Open the reply composer on the FIRST post container only.

    Critical: do not let `Reply` matches inside the reply list below win. We
    scope every selector to the first post container.

    Returns the name of the selector strategy that succeeded.
    """
    scope, scope_sel = await _first_post_container(page)

    strategies: list[tuple[str, Any]] = [
        (
            f"{scope_sel} >> get_by_role(button, name=/^reply$/i)",
            scope.get_by_role("button", name=re.compile(r"^reply$", re.I)).first,
        ),
        (
            f"{scope_sel} >> svg[aria-label='Reply'] -> ancestor [role=button|tabindex=0]",
            scope.locator("svg[aria-label='Reply']")
            .first.locator("xpath=ancestor::div[@role='button' or @tabindex='0'][1]")
            .first,
        ),
        (
            f"{scope_sel} >> [aria-label='Reply']",
            scope.locator("[aria-label='Reply']").first,
        ),
        (
            f"{scope_sel} >> [role='button']:has-text('Reply')",
            scope.locator("[role='button']:has-text('Reply')").first,
        ),
        # Last-ditch: any Reply icon on the page (first one is usually the parent)
        (
            "page >> svg[aria-label='Reply'] (first global)",
            page.locator("svg[aria-label='Reply']")
            .first.locator("xpath=ancestor::div[@role='button' or @tabindex='0'][1]")
            .first,
        ),
    ]

    last_err: Exception | None = None
    for label, loc in strategies:
        try:
            await loc.wait_for(state="visible", timeout=4000)
            await loc.click()
            _log(f"clicked reply button via selector: {label}")
            return label
        except Exception as e:  # noqa: BLE001
            last_err = e
            _log(f"reply selector failed [{label}]: {type(e).__name__}: {e}")
            continue

    raise RuntimeError(
        f"Could not find Reply button on the FIRST article. Last error: {last_err}"
    )


async def _focus_composer(page: Page) -> tuple[Any, str]:
    """Locate + focus the compose textbox. Returns (locator, selector_label)."""
    strategies: list[tuple[str, Any]] = [
        ("get_by_role(textbox)", page.get_by_role("textbox").last),
        ("[data-lexical-editor='true']", page.locator("[data-lexical-editor='true']").last),
        (
            "[role='textbox'][contenteditable='true']",
            page.locator("[role='textbox'][contenteditable='true']").last,
        ),
        ("div[contenteditable='true']", page.locator("div[contenteditable='true']").last),
    ]
    last_err: Exception | None = None
    for label, loc in strategies:
        try:
            await loc.wait_for(state="visible", timeout=5000)
            await loc.click()
            _log(f"composer focused via: {label}")
            return loc, label
        except Exception as e:  # noqa: BLE001
            last_err = e
            _log(f"composer selector failed [{label}]: {type(e).__name__}: {e}")
            continue
    raise RuntimeError(
        f"Reply composer didn't open (no usable textbox). Last error: {last_err}"
    )


async def _composer_text_length(page: Page) -> int:
    """Best-effort: read innerText length of whichever editor we focused."""
    try:
        n = await page.evaluate(
            """() => {
                const el = document.querySelector(
                    "[data-lexical-editor='true'], [role='textbox'][contenteditable='true'], div[contenteditable='true']"
                );
                return el ? (el.innerText || '').length : -1;
            }"""
        )
        return int(n)
    except Exception:
        return -1


async def _find_post_button(page: Page) -> tuple[Any, str]:
    """Locate the Post submit button (the modal one). Prefer the last visible match."""
    strategies: list[tuple[str, Any]] = [
        (
            "get_by_role(button, name=/^post$/i).last",
            page.get_by_role("button", name=re.compile(r"^post$", re.I)).last,
        ),
        ("[aria-label='Post']:last", page.locator("[aria-label='Post']").last),
        (
            "div[role='button']:has-text('Post'):last",
            page.locator("div[role='button']:has-text('Post')").last,
        ),
    ]
    last_err: Exception | None = None
    for label, loc in strategies:
        try:
            await loc.wait_for(state="visible", timeout=4000)
            return loc, label
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise RuntimeError(f"Could not locate Post submit button. Last error: {last_err}")


async def _wait_enabled(btn: Any, total_ms: int = 6000) -> bool:
    """Poll aria-disabled / disabled until the button is clickable."""
    deadline = time.monotonic() + total_ms / 1000.0
    while time.monotonic() < deadline:
        try:
            aria = await btn.get_attribute("aria-disabled")
            disabled = await btn.get_attribute("disabled")
            if aria != "true" and disabled is None:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.2)
    return False


# ──────────────────────────────────────────────────────────────────────────
# Response capture (best-effort)
# ──────────────────────────────────────────────────────────────────────────

def _find_shortcode(node: Any) -> str | None:
    if isinstance(node, dict):
        for key in ("code", "shortcode"):
            v = node.get(key)
            if isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]{6,}", v):
                return v
        for v in node.values():
            r = _find_shortcode(v)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_shortcode(v)
            if r:
                return r
    return None


def _find_pk(node: Any) -> str | None:
    if isinstance(node, dict):
        for key in ("pk", "id"):
            v = node.get(key)
            if isinstance(v, (str, int)):
                s = str(v)
                if s.isdigit() and len(s) >= 10:
                    return s
        for v in node.values():
            r = _find_pk(v)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_pk(v)
            if r:
                return r
    return None


async def _grab_create_response(page: Page, click_submit) -> tuple[str | None, str | None, str | None]:
    """Watch network while submit fires. Returns (shortcode, pk, response_url_snippet)."""
    try:
        async with page.expect_response(
            lambda r: (
                r.request.method == "POST"
                and (
                    "barcelona_post_create" in r.url.lower()
                    or "/api/graphql" in r.url
                    or ("create" in r.url.lower() and "post" in r.url.lower())
                )
            ),
            timeout=20000,
        ) as resp_info:
            await click_submit()
        resp = await resp_info.value
        url_snip = resp.url[-120:]
        _log(f"network response captured: …{url_snip}")
        try:
            data = await resp.json()
        except Exception:
            try:
                txt = await resp.text()
                data = json.loads(txt.lstrip("for (;;);").strip())
            except Exception:
                _log("response body was not JSON")
                return None, None, url_snip
        return _find_shortcode(data), _find_pk(data), url_snip
    except PlaywrightTimeout:
        _log("no GraphQL response matched within 20s — falling back to DOM verification")
        try:
            await click_submit()
        except Exception as e:  # noqa: BLE001
            _log(f"submit click after timeout raised: {e}")
        return None, None, None


# ──────────────────────────────────────────────────────────────────────────
# Verification — the new source of truth
# ──────────────────────────────────────────────────────────────────────────

async def _verify_reply_on_parent(
    page: Page, parent_url: str, our_username: str, timeout_s: float = 15.0
) -> str | None:
    """Re-visit the parent post and look for an anchor to @<our_username>/post/.

    Returns the new reply URL (absolute) if found, else None. This is DOM proof
    that the reply is actually live — no stale-profile fallback.
    """
    _log(f"verifying reply on parent: {parent_url}")
    try:
        await page.goto(parent_url, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:  # noqa: BLE001
        _log(f"verify nav failed: {e}")
        return None

    # Give replies a beat to hydrate + scroll to encourage rendering
    deadline = time.monotonic() + timeout_s
    selector = f"a[href*='/@{our_username}/post/']"
    while time.monotonic() < deadline:
        try:
            await page.evaluate("window.scrollBy(0, 600)")
        except Exception:
            pass
        try:
            href = await page.evaluate(
                """(sel) => {
                    const a = document.querySelector(sel);
                    return a ? a.getAttribute('href') : null;
                }""",
                selector,
            )
        except Exception:
            href = None
        if href:
            if href.startswith("/"):
                href = "https://www.threads.net" + href
            _log(f"verification HIT — found reply anchor: {href}")
            return href
        await asyncio.sleep(0.75)

    _log(f"verification MISS — no anchor matching {selector} within {timeout_s}s")
    return None


# ──────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────

async def post_threads_reply(item: dict[str, Any]) -> dict[str, str | None]:
    """Publish a reply to Threads via the web UI.

    On success, the returned reply_url is DOM-verified to exist on the parent
    post. On any failure, raises RuntimeError with the reason.
    """
    text = item.get("final_text") or item.get("draft_text")
    parent_url = _normalize_threads_url(item.get("parent_post_url") or "")
    parent_id = item.get("parent_post_id")
    if not text:
        raise RuntimeError(f"item #{item.get('id')} has no draft_text/final_text")
    if not parent_url and not parent_id:
        raise RuntimeError(
            f"item #{item.get('id')} has no parent_post_url or parent_post_id"
        )

    brand = load_brand_profile()
    our_username = brand["accounts"]["threads"]["username"]
    cookies_path = _cookies_path(our_username)
    if not cookies_path.exists():
        raise RuntimeError(
            f"Threads cookies missing at {cookies_path}. "
            f"Run `python -m src.cli threads-login`."
        )

    with cookies_path.open() as f:
        cookies = json.load(f)
    if "sessionid" not in cookies:
        raise RuntimeError(
            "Threads cookies missing required key (sessionid). Re-run threads-login."
        )

    if not parent_url:
        parent_url = f"https://www.threads.net/t/{parent_id}"

    dry_run = _env_bool("THREADS_POST_DRY_RUN", default=False)
    if dry_run:
        _log("DRY-RUN mode active — will abort right before the final Post click")

    async with async_playwright() as pw:
        browser, ctx = await _new_logged_in_context(pw, cookies)
        try:
            page = await ctx.new_page()

            # ─── Step 1: nav to parent ────────────────────────────────────
            try:
                await page.goto(parent_url, wait_until="domcontentloaded", timeout=30000)
                _log(f"navigated to parent post: {page.url}")
            except PlaywrightTimeout:
                raise RuntimeError(f"Timed out loading {parent_url}")

            if "/login" in page.url:
                raise RuntimeError(
                    f"Threads session expired (redirected to {page.url}). "
                    f"Re-run threads-login."
                )

            try:
                await page.wait_for_selector(
                    "article, [data-pressable-container]", timeout=15000
                )
            except PlaywrightTimeout:
                await _shot(page, "00-parent-no-article")
                raise RuntimeError(
                    f"Parent post did not render at {parent_url} "
                    "(deleted/private/blocked?)"
                )

            # Quick parent-post diagnostics
            try:
                article_count = await page.locator("article").count()
                pressable_count = await page.locator("[data-pressable-container]").count()
                first_author_handle = await page.evaluate(
                    """() => {
                        const a = document.querySelector(
                            "article a[href^='/@'], [data-pressable-container] a[href^='/@'], main a[href^='/@']"
                        );
                        return a ? a.getAttribute('href') : null;
                    }"""
                )
                _log(
                    f"found {article_count} article(s) / {pressable_count} pressable container(s); "
                    f"first author href = {first_author_handle}"
                )
            except Exception as e:  # noqa: BLE001
                _log(f"parent-post diagnostics failed: {e}")

            await _shot(page, "01-parent-loaded")

            # ─── Step 2: open reply composer ──────────────────────────────
            try:
                reply_selector = await _click_reply_button(page)
            except Exception as e:
                await _shot(page, "02-reply-click-failed")
                raise RuntimeError(f"reply button click failed: {e}") from e

            # ─── Step 3: focus composer + type ────────────────────────────
            try:
                composer_loc, composer_sel = await _focus_composer(page)
            except Exception as e:
                await _shot(page, "03-composer-not-found")
                raise RuntimeError(f"composer locate/focus failed: {e}") from e

            await _shot(page, "03-composer-open")

            await page.keyboard.type(text, delay=15)
            await asyncio.sleep(0.4)
            length_after = await _composer_text_length(page)
            _log(
                f"composer focused via {composer_sel}; "
                f"typed {len(text)} chars; innerText length now = {length_after}"
            )
            await _shot(page, "04-after-typing")

            # ─── Step 4: locate Post button, wait for enabled ─────────────
            try:
                post_btn, post_sel = await _find_post_button(page)
            except Exception as e:
                await _shot(page, "05-post-btn-missing")
                raise RuntimeError(f"post button not found: {e}") from e

            enabled = await _wait_enabled(post_btn, total_ms=6000)
            try:
                aria_dis = await post_btn.get_attribute("aria-disabled")
            except Exception:
                aria_dis = "?"
            _log(
                f"post button located via {post_sel}; "
                f"aria-disabled={aria_dis}; enabled_after_wait={enabled}"
            )
            await _shot(page, "05-before-submit")

            if not enabled:
                raise RuntimeError(
                    "Post button never became enabled (aria-disabled stayed true)."
                )

            # ─── DRY-RUN abort hook ───────────────────────────────────────
            if dry_run:
                _log("DRY-RUN: aborting before final Post click")
                await _shot(page, "06-dryrun-abort")
                raise RuntimeError("dry-run: aborting before submit")

            # ─── Step 5: click Post while watching network ────────────────
            _log("post button clicked, waiting for response/navigation")
            shortcode, pk, resp_snip = await _grab_create_response(
                page, lambda: post_btn.click()
            )

            # Snapshot post-submit state
            try:
                await asyncio.sleep(1.5)
                await _shot(page, "07-after-submit")
                _log(f"post-submit URL: {page.url}")
            except Exception:
                pass

            # ─── Step 6: VERIFY on the parent post ────────────────────────
            verified_url = await _verify_reply_on_parent(
                page, parent_url, our_username, timeout_s=15.0
            )
            await _shot(page, "08-verify-parent")

            if not verified_url:
                # Hard fail — no stale-profile fallback as "proof".
                raise RuntimeError(
                    "post not visible on parent post within 15s "
                    f"(network_hint={resp_snip!r}, graphql_shortcode={shortcode!r}, "
                    f"graphql_pk={pk!r})"
                )

            # Extract canonical shortcode from the verified anchor
            m = _POST_URL_RE.search(verified_url) or _SHORTCODE_RE.search(verified_url)
            if m:
                verified_shortcode = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)
            else:
                verified_shortcode = shortcode or pk

            reply_id = verified_shortcode or shortcode or pk
            if not reply_id:
                raise RuntimeError(
                    "verified anchor found but could not parse shortcode from it"
                )

            reply_url = (
                f"https://www.threads.net/@{our_username}/post/{verified_shortcode}"
                if verified_shortcode
                else verified_url
            )
            _log(f"SUCCESS — verified reply at {reply_url}")
            return {"reply_platform_id": reply_id, "reply_url": reply_url}
        finally:
            await ctx.close()
            await browser.close()
