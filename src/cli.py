"""OpenCraft social bot CLI — unified entrypoint.

Usage:
    python -m src.cli <command> [options]

Commands map 1:1 to the trigger phrases in CLAUDE.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.brand.loader import load_brand_profile, summarize_brand
from src.queue.db import (
    DB_PATH,
    init_db,
    list_items,
    count_today,
    set_status,
    save_draft,
    mark_draft_failed,
    insert_scraped,
    last_scrape_at,
    queue_counts,
    get_item,
    mark_posted,
    mark_post_failed,
)


def cmd_status(args) -> int:
    init_db()
    brand = load_brand_profile()
    caps = brand["operational_caps"]["replies_per_day"]

    print("=== OpenCraft Social Bot — Status ===")
    print(f"Brand:         {brand['brand_name']} — {brand['tagline']}")
    print(f"DB:            {DB_PATH}")
    print()
    print("Daily reply counts (posted today):")
    for platform, cap in caps.items():
        n = count_today(platform=platform, status="posted")
        bar = "█" * n + "░" * (cap - n)
        print(f"  {platform:10s} {n}/{cap}  {bar}")
    print()
    print("Queue depth by status:")
    for status in ["scraped", "draft_pending", "ready_for_review", "approved", "failed"]:
        n = count_today(status=status)
        if n:
            print(f"  {status:20s} {n}")
    print()
    print("Tip: `python -m src.cli queue --status ready_for_review` to see drafts")
    return 0


def cmd_brand_show(args) -> int:
    brand = load_brand_profile()
    print(json.dumps(summarize_brand(brand), indent=2, ensure_ascii=False))
    return 0


def cmd_scrape(args) -> int:
    import asyncio
    from dotenv import load_dotenv

    load_dotenv()
    init_db()
    brand = load_brand_profile()

    if getattr(args, "lax", False):
        # Disarm hard thresholds for testing the pipeline end-to-end
        brand = dict(brand)
        brand["viral_post_filters"] = dict(brand.get("viral_post_filters", {}))
        brand["viral_post_filters"]["max_post_age_hours"] = None
        brand["viral_post_filters"]["min_engagement"] = {
            "threads": {"min_likes": 0, "engagement_proxy": "has_replies=true"},
            "x": {"min_likes": 0, "min_replies": 0},
        }
        print("(--lax: age & engagement filters disabled; anti-topics + spam still active)")

    platforms = ["threads", "x"] if args.platform == "all" else [args.platform]
    print(f"→ scrape requested for: {', '.join(platforms)} (limit {args.limit})")

    inserted_total = 0
    skipped_total = 0

    for platform in platforms:
        print(f"\n[{platform}]")
        try:
            if platform == "threads":
                from src.scraper.threads_spider import scrape_threads_viral

                posts = asyncio.run(scrape_threads_viral(brand, limit=args.limit))
                account_username = brand["accounts"]["threads"]["username"]

            elif platform == "x":
                from src.scraper.x_spider import scrape_x_viral

                posts = asyncio.run(scrape_x_viral(brand, limit=args.limit))
                account_username = brand["accounts"]["x_twitter"]["username"]

            else:
                print(f"  [skipped] unknown platform: {platform}")
                continue
        except RuntimeError as e:
            print(f"  [error] {e}")
            continue
        except Exception as e:
            print(f"  [error] {platform} scraper crashed: {e.__class__.__name__}: {e}")
            continue

        platform_inserted = 0
        platform_deduped = 0
        for p in posts:
            row_id = insert_scraped(
                platform=platform,
                account_username=account_username,
                parent_post_id=p.parent_post_id,
                parent_post_url=p.parent_post_url,
                parent_post_text=p.parent_post_text,
                parent_author=p.parent_author,
                parent_likes=p.parent_likes,
                parent_replies=p.parent_replies,
                parent_created_at=p.created_at,
                note=f"keyword={p.keyword}",
            )
            if row_id:
                platform_inserted += 1
            else:
                platform_deduped += 1

        print(f"  → kept {len(posts)} after filters | inserted {platform_inserted} | deduped {platform_deduped}")
        inserted_total += platform_inserted
        skipped_total += platform_deduped

    print(f"\n✓ total inserted: {inserted_total}, deduped: {skipped_total}")
    print("Next: `python -m src.cli queue --status scraped`")
    return 0


def cmd_draft(args) -> int:
    """Drafting is owned by the `reply-drafter` custom subagent (see .claude/agents/).

    This CLI command no longer does drafting itself. It only reports what's
    pending and how to invoke the subagent.
    """
    init_db()
    pending = list_items(status="scraped", limit=200)
    print(f"→ {len(pending)} item(s) waiting for drafts (status=scraped)")
    print()
    print("Drafting is handled by the `reply-drafter` custom subagent.")
    print("To draft replies, do ONE of:")
    print()
    print("  • In a Claude Code session in this repo, say:")
    print('      \"draft replies\"   or   \"draft #<id>\"')
    print("    The brain (CLAUDE.md) will invoke the reply-drafter subagent.")
    print()
    print("  • Or invoke directly:")
    print('      Task tool with subagent_type=\"reply-drafter\"')
    print()
    print("The subagent uses these helper CLIs:")
    print("  python -m src.cli list-scraped --limit N        # read queue as JSON")
    print("  python -m src.cli save-draft --id N --mode M    # save draft (text via stdin)")
    return 0


def cmd_list_scraped(args) -> int:
    """Emit queued items as JSON for the reply-drafter subagent."""
    import json
    from src.scraper.filters import detect_language
    init_db()
    items = list_items(status="scraped", platform=args.platform, limit=args.limit)
    if args.id:
        items = [i for i in items if i["id"] == args.id]
        if not items:
            all_items = list_items(status=None, limit=1000)
            items = [i for i in all_items if i["id"] == args.id]

    brand = load_brand_profile()
    audience_map = brand.get("viral_post_filters", {}).get("audience_keyword_map", {}) or {}

    def audience_for(note: str | None) -> str:
        kw = (note or "").replace("keyword=", "").strip().lower()
        for aud, kws in audience_map.items():
            if kw in {k.lower() for k in kws}:
                return aud
        return "unknown"

    out = []
    for it in items:
        text = it.get("parent_post_text") or ""
        lang, lang_conf = detect_language(text)
        # Normalize anything that isn't id/en to 'und' for clearer subagent UX
        if lang not in {"id", "en"}:
            lang = "und"
        out.append({
            "id": it["id"],
            "platform": it["platform"],
            "account_username": it["account_username"],
            "parent_post_id": it["parent_post_id"],
            "parent_post_url": it["parent_post_url"],
            "parent_post_text": text,
            "parent_author": it["parent_author"],
            "parent_likes": it["parent_likes"],
            "parent_replies": it["parent_replies"],
            "parent_created_at": it.get("parent_created_at"),
            "parent_lang": lang,
            "parent_lang_confidence": round(lang_conf, 2),
            "keyword": (it.get("note") or "").replace("keyword=", "").strip(),
            "audience": audience_for(it.get("note")),
            "status": it["status"],
        })
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_save_draft(args) -> int:
    """Read draft text from stdin and persist it. Used by reply-drafter subagent."""
    import sys
    init_db()
    text = sys.stdin.read().strip()
    if not text:
        print("✗ no draft text on stdin")
        return 1
    if args.mark_failed:
        mark_draft_failed(args.id, text)
        print(f"✓ marked #{args.id} failed")
        return 0
    # length safety per platform
    item = next((i for i in list_items(status=None, limit=2000) if i["id"] == args.id), None)
    if not item:
        print(f"✗ no item with id={args.id}")
        return 1
    max_chars = 270 if item["platform"] == "x" else 480
    if len(text) > max_chars:
        print(f"✗ draft too long ({len(text)} chars, max {max_chars}) — regenerate a shorter version")
        return 1
    save_draft(args.id, args.mode, text)
    print(f"✓ saved draft for #{args.id} (mode={args.mode}, {len(text)} chars)")
    return 0


def cmd_queue(args) -> int:
    init_db()
    items = list_items(status=args.status, platform=args.platform, limit=args.limit)
    if not items:
        print(f"(no items with status={args.status})")
        return 0
    for item in items:
        print(f"[{item['id']}] {item['platform']} · @{item['parent_author'] or '?'} · {item['status']}")
        if item.get("parent_post_text"):
            print(f"   POST: {item['parent_post_text'][:160]}")
        if item.get("draft_text"):
            print(f"   DRAFT: {item['draft_text']}")
        print()
    return 0


def cmd_approve(args) -> int:
    init_db()
    set_status(args.id, "approved")
    print(f"✓ Item #{args.id} approved. Use `python -m src.cli post --id {args.id}` to publish.")
    return 0


def cmd_skip(args) -> int:
    init_db()
    set_status(args.id, "skipped", note=args.reason)
    print(f"✓ Item #{args.id} skipped.")
    return 0


def _dispatch_post(item: dict) -> dict:
    """Route an item to the right poster. Returns the poster's result dict."""
    import asyncio

    platform = item["platform"]
    if platform == "threads":
        from src.poster.threads_poster import post_threads_reply

        return asyncio.run(post_threads_reply(item))
    if platform == "x":
        from src.poster.x_poster import post_x_reply

        return asyncio.run(post_x_reply(item))
    raise RuntimeError(f"unknown platform: {platform}")


def _post_single(item: dict, brand: dict) -> int:
    """Post one item. Returns 0 on success, 1 on failure."""
    item_id = item["id"]
    platform = item["platform"]
    text = item.get("final_text") or item.get("draft_text")

    if item["status"] != "approved":
        print(f"✗ #{item_id} is status={item['status']!r} — only `approved` items can be posted.")
        print(f"  Run: python -m src.cli approve --id {item_id}")
        return 1
    if not text:
        print(f"✗ #{item_id} has no draft_text/final_text — nothing to post.")
        mark_post_failed(item_id, "no draft text")
        return 1

    # Daily cap check
    cap = brand["operational_caps"]["replies_per_day"].get(platform)
    if cap is not None:
        posted_today = count_today(platform=platform, status="posted")
        if posted_today >= cap:
            print(
                f"✗ Daily cap reached for {platform}: {posted_today}/{cap}. "
                f"Try again tomorrow."
            )
            return 1

    print(f"→ posting #{item_id} to {platform} ({len(text)} chars)…")
    try:
        result = _dispatch_post(item)
    except Exception as e:
        err = f"{e.__class__.__name__}: {e}"
        print(f"✗ post #{item_id} failed — {err}")
        mark_post_failed(item_id, err)
        return 1

    reply_id = result.get("reply_platform_id")
    reply_url = result.get("reply_url")
    if not reply_id:
        err = f"poster returned no reply_platform_id: {result}"
        print(f"✗ {err}")
        mark_post_failed(item_id, err)
        return 1

    mark_posted(item_id, reply_platform_id=reply_id, reply_url=reply_url, final_text=text)
    print(f"✓ #{item_id} posted to {platform}")
    print(f"   reply id:  {reply_id}")
    if reply_url:
        print(f"   reply url: {reply_url}")
    return 0


def cmd_post(args) -> int:
    import random
    import time
    from dotenv import load_dotenv

    load_dotenv()
    init_db()
    brand = load_brand_profile()
    caps_cfg = brand["operational_caps"]
    min_delay = caps_cfg.get("min_delay_between_replies_seconds", 90)
    max_delay = caps_cfg.get("max_delay_between_replies_seconds", 300)

    if args.id and args.all_approved:
        print("✗ Use either --id <n> or --all-approved, not both.")
        return 2

    if args.id:
        item = get_item(args.id)
        if not item:
            print(f"✗ no item with id={args.id}")
            return 1
        return _post_single(item, brand)

    if args.all_approved:
        approved = list_items(status="approved", limit=200)
        if not approved:
            print("(no items with status=approved)")
            return 0
        # Post oldest-first so the queue drains in order
        approved.sort(key=lambda i: i["id"])
        print(f"→ posting {len(approved)} approved item(s), throttled {min_delay}-{max_delay}s between")
        ok = 0
        for idx, item in enumerate(approved):
            rc = _post_single(item, brand)
            if rc == 0:
                ok += 1
            if idx < len(approved) - 1:
                delay = random.randint(min_delay, max_delay)
                print(f"   sleeping {delay}s before next post…")
                time.sleep(delay)
        print(f"\n✓ posted {ok}/{len(approved)}")
        return 0 if ok == len(approved) else 1

    print("Specify --id <n> or --all-approved")
    return 2


def cmd_scrapers(args) -> int:
    """Health check + diagnostics for both scrapers."""
    import asyncio
    import json
    from pathlib import Path
    from dotenv import load_dotenv
    from playwright.async_api import async_playwright

    load_dotenv()
    init_db()
    brand = load_brand_profile()

    print("=== SCRAPERS HEALTH ===\n")

    # --- Brand inputs ---
    keywords = brand["viral_post_filters"]["monitor_keywords"]
    anti = brand["niche"]["anti_topics"]
    skip_words = brand["viral_post_filters"].get("skip_if_post_contains", [])
    print(f"Brand:              {brand['brand_name']}")
    print(f"Keywords:           {len(keywords)}  ({', '.join(keywords[:6])}{'…' if len(keywords) > 6 else ''})")
    print(f"Anti-topics:        {len(anti)}")
    print(f"Spam skip-words:    {len(skip_words)}")
    print(f"Max post age:       {brand['viral_post_filters'].get('max_post_age_hours')}h")
    me = brand["viral_post_filters"].get("min_engagement", {})
    print(f"Min engagement:     threads≥{me.get('threads', {}).get('min_likes', 0)}♥  "
          f"x≥{me.get('x', {}).get('min_likes', 0)}♥/{me.get('x', {}).get('min_replies', 0)}💬")
    print()

    # --- Threads scraper ---
    print("[threads]")
    print(f"  account:          @{brand['accounts']['threads']['username']}")
    print(f"  auth required:    no (uses public search SERP)")
    last = last_scrape_at("threads")
    print(f"  last scrape at:   {last or '(never)'}")
    counts = queue_counts()
    for status in ("scraped", "draft_pending", "ready_for_review", "approved", "posted", "failed", "skipped"):
        n = counts.get(("threads", status), 0)
        if n:
            print(f"  {status:18s} {n}")
    print()

    # --- X scraper ---
    print("[x]")
    username = brand["accounts"]["x_twitter"]["username"]
    print(f"  account:          @{username}")
    cookies_path = Path(__file__).resolve().parents[1] / "accounts" / f"x_{username}.cookies.json"
    if cookies_path.exists():
        try:
            with cookies_path.open() as f:
                cookies = json.load(f)
            ok = {"auth_token", "ct0"}.issubset(cookies.keys())
            print(f"  cookies file:     {cookies_path.name}  ({len(cookies)} keys, {'OK' if ok else 'MISSING REQUIRED'})")
        except Exception as e:
            print(f"  cookies file:     ERROR reading: {e}")
    else:
        print(f"  cookies file:     ✗ MISSING — run `python -m src.cli x-paste-cookies`")

    last = last_scrape_at("x")
    print(f"  last scrape at:   {last or '(never)'}")
    for status in ("scraped", "draft_pending", "ready_for_review", "approved", "posted", "failed", "skipped"):
        n = counts.get(("x", status), 0)
        if n:
            print(f"  {status:18s} {n}")
    print()

    # --- Live session probe (optional but informative) ---
    if args.probe and cookies_path.exists():
        print("[x] live probe (Playwright)…")
        from src.scraper.x_spider import _to_playwright_cookies

        async def probe() -> str:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                ctx = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 900},
                    locale="en-US",
                )
                with cookies_path.open() as f:
                    await ctx.add_cookies(_to_playwright_cookies(json.load(f)))
                page = await ctx.new_page()
                try:
                    await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=15000)
                    url = page.url
                finally:
                    await ctx.close()
                    await browser.close()
                return url

        try:
            url = asyncio.run(probe())
            ok = "/flow/login" not in url and "/login" not in url
            print(f"   {'✓ session valid' if ok else '✗ session expired / login wall'}  (URL: {url})")
        except Exception as e:
            print(f"   ✗ probe failed: {e.__class__.__name__}: {e}")
        print()

    print("Tips:")
    print("  - Run a scrape:  python -m src.cli scrape --platform all")
    print("  - Lax filters:   python -m src.cli scrape --platform all --lax")
    print("  - Live probe:    python -m src.cli scrapers --probe")
    return 0


def cmd_x_login(args) -> int:
    """Open a visible browser → you log in once → bot captures cookies for twikit."""
    import asyncio
    import json
    from pathlib import Path
    from playwright.async_api import async_playwright

    brand = load_brand_profile()
    username = brand["accounts"]["x_twitter"]["username"]
    accounts_dir = Path(__file__).resolve().parents[1] / "accounts"
    accounts_dir.mkdir(parents=True, exist_ok=True)
    cookies_path = accounts_dir / f"x_{username}.cookies.json"

    required_keys = {"auth_token", "ct0"}
    target_domain = "x.com"

    print(f"→ Opening visible browser. Log in as @{username}.")
    print(f"  The bot will detect successful login and save cookies to {cookies_path.name}.")
    print(f"  Window will close automatically. Just don't close it manually.\n")

    async def main() -> int:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            page = await ctx.new_page()
            await page.goto("https://x.com/login")
            print("  · waiting for login (max 5 minutes)…")

            # Poll cookies until both required ones appear (any URL change)
            timeout_seconds = 300
            interval = 2
            elapsed = 0
            cookies_dict: dict[str, str] = {}

            while elapsed < timeout_seconds:
                cookies_list = await ctx.cookies()
                cookies_dict = {
                    c["name"]: c["value"]
                    for c in cookies_list
                    if c.get("domain", "").endswith(target_domain)
                }
                missing = required_keys - set(cookies_dict.keys())
                if not missing and cookies_dict.get("auth_token"):
                    # auth_token usually appears AFTER successful login
                    break
                await asyncio.sleep(interval)
                elapsed += interval

            if required_keys - set(cookies_dict.keys()):
                print(f"  ✗ Timed out — required cookies not detected ({sorted(required_keys)}).")
                await browser.close()
                return 1

            with cookies_path.open("w") as f:
                json.dump(cookies_dict, f, indent=2)

            print(f"\n  ✓ Captured {len(cookies_dict)} cookies for {target_domain}")
            print(f"    Saved to {cookies_path}")
            print("    Closing browser…")
            await asyncio.sleep(1.5)
            await browser.close()
            return 0

    rc = asyncio.run(main())
    if rc == 0:
        print("\n→ Verifying cookies with twikit…")
        return cmd_x_test(args)
    return rc


def cmd_x_test(args) -> int:
    """Verify saved X cookies work — uses Playwright (not twikit, which is broken)."""
    import asyncio
    import json
    from pathlib import Path
    from playwright.async_api import async_playwright

    brand = load_brand_profile()
    username = brand["accounts"]["x_twitter"]["username"]
    cookies_path = Path(__file__).resolve().parents[1] / "accounts" / f"x_{username}.cookies.json"

    if not cookies_path.exists():
        print(f"✗ No cookies at {cookies_path}")
        print("  Run: python -m src.cli x-paste-cookies")
        return 1

    with cookies_path.open() as f:
        cookies = json.load(f)
    print(f"Loaded {len(cookies)} cookies from {cookies_path.name}")
    print(f"Keys: {sorted(cookies.keys())}")

    from src.scraper.x_spider import _to_playwright_cookies

    async def main() -> int:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            await ctx.add_cookies(_to_playwright_cookies(cookies))
            page = await ctx.new_page()
            try:
                await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=20000)
                # If logged in, the URL stays /home; if not, redirects to /i/flow/login
                final = page.url
                if "/flow/login" in final or "/login" in final:
                    print(f"✗ cookies invalid — got redirected to {final}")
                    return 1
                # Try to read the profile link from the side nav
                handle = await page.evaluate(
                    """() => {
                        const a = document.querySelector("a[data-testid='AppTabBar_Profile_Link']");
                        return a ? a.getAttribute('href') : '';
                    }"""
                )
                print(f"✓ logged in (URL: {final})")
                if handle:
                    print(f"  profile link: x.com{handle}")
                return 0
            except Exception as e:
                print(f"✗ session check failed: {e.__class__.__name__}: {e}")
                return 1
            finally:
                await ctx.close()
                await browser.close()

    return asyncio.run(main())


def cmd_threads_login(args) -> int:
    """Open a visible browser → log in as @opencraft.dev → bot saves Threads cookies."""
    import asyncio
    import json
    from pathlib import Path
    from playwright.async_api import async_playwright

    brand = load_brand_profile()
    username = brand["accounts"]["threads"]["username"]
    accounts_dir = Path(__file__).resolve().parents[1] / "accounts"
    accounts_dir.mkdir(parents=True, exist_ok=True)
    cookies_path = accounts_dir / f"threads_{username}.cookies.json"

    # `sessionid` is the auth cookie. `ig_did` + `csrftoken` are the supporting
    # cookies that Threads/IG share via Meta's auth stack. We require all three.
    required_keys = {"sessionid", "ig_did", "csrftoken"}
    # Threads issues cookies for both .threads.net and .instagram.com — we capture
    # any cookie scoped to either host.
    target_domains = ("threads.net", "instagram.com", "threads.com")

    print(f"→ Opening visible browser. Log in as @{username}.")
    print(f"  Google/Instagram SSO is fine. The bot detects login and saves to")
    print(f"  {cookies_path.name}. Don't close the window manually.\n")

    async def main() -> int:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            page = await ctx.new_page()
            await page.goto("https://www.threads.net/login")
            print("  · waiting for login (max 5 minutes)…")

            timeout_seconds = 300
            interval = 2
            elapsed = 0
            cookies_dict: dict[str, str] = {}

            while elapsed < timeout_seconds:
                cookies_list = await ctx.cookies()
                cookies_dict = {}
                for c in cookies_list:
                    dom = c.get("domain", "").lstrip(".")
                    if any(dom.endswith(d) for d in target_domains):
                        # Last-write wins — fine because Meta issues consistent values
                        cookies_dict[c["name"]] = c["value"]
                if required_keys.issubset(cookies_dict.keys()):
                    break
                await asyncio.sleep(interval)
                elapsed += interval

            missing = required_keys - set(cookies_dict.keys())
            if missing:
                print(
                    f"  ✗ Timed out — required cookies not detected. "
                    f"Missing: {sorted(missing)}"
                )
                await browser.close()
                return 1

            with cookies_path.open("w") as f:
                json.dump(cookies_dict, f, indent=2)

            print(f"\n  ✓ Captured {len(cookies_dict)} cookies (sessionid + supports)")
            print(f"    Saved to {cookies_path}")

            # Quick verification: open a fresh page, confirm we're not on /login
            print("  · verifying session…")
            verify_page = await ctx.new_page()
            try:
                await verify_page.goto(
                    "https://www.threads.net/",
                    wait_until="domcontentloaded",
                    timeout=20000,
                )
                final = verify_page.url
                if "/login" in final:
                    print(f"  ✗ Session check failed — landed on {final}")
                    await browser.close()
                    return 1
                print(f"  ✓ Session valid (URL: {final})")
            except Exception as e:
                print(f"  ! Could not verify session: {e.__class__.__name__}: {e}")

            print("    Closing browser…")
            await asyncio.sleep(1.5)
            await browser.close()
            return 0

    return asyncio.run(main())


def cmd_threads_test(args) -> int:
    """Verify saved Threads cookies still produce a logged-in session."""
    import asyncio
    import json
    from pathlib import Path
    from playwright.async_api import async_playwright

    brand = load_brand_profile()
    username = brand["accounts"]["threads"]["username"]
    cookies_path = (
        Path(__file__).resolve().parents[1]
        / "accounts"
        / f"threads_{username}.cookies.json"
    )

    if not cookies_path.exists():
        print(f"✗ No cookies at {cookies_path}")
        print("  Run: python -m src.cli threads-login")
        return 1

    with cookies_path.open() as f:
        cookies = json.load(f)
    print(f"Loaded {len(cookies)} cookies from {cookies_path.name}")
    print(f"Keys: {sorted(cookies.keys())}")

    has_session = "sessionid" in cookies
    has_csrf = "csrftoken" in cookies
    has_did = "ig_did" in cookies
    print(
        f"  sessionid={'✓' if has_session else '✗'}  "
        f"ig_did={'✓' if has_did else '✗'}  "
        f"csrftoken={'✓' if has_csrf else '✗'}"
    )
    if not has_session:
        print("✗ Missing primary auth cookie (sessionid). Re-run threads-login.")
        return 1

    from src.poster.threads_poster import _to_playwright_cookies_threads

    async def main() -> int:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            await ctx.add_cookies(_to_playwright_cookies_threads(cookies))
            page = await ctx.new_page()
            try:
                await page.goto(
                    "https://www.threads.net/",
                    wait_until="domcontentloaded",
                    timeout=20000,
                )
                final = page.url
                if "/login" in final:
                    print(f"✗ cookies invalid — got redirected to {final}")
                    return 1
                print(f"✓ logged in (URL: {final})")
                return 0
            except Exception as e:
                print(f"✗ session check failed: {e.__class__.__name__}: {e}")
                return 1
            finally:
                await ctx.close()
                await browser.close()

    return asyncio.run(main())


def _save_x_cookies(data: dict) -> tuple[int, str]:
    """Shared validator + writer for X cookies. Returns (exit_code, message)."""
    import json
    from pathlib import Path

    if not isinstance(data, dict):
        # Accept Playwright/EditThisCookie format (list of objects) too
        if isinstance(data, list):
            data = {
                c["name"]: c["value"]
                for c in data
                if isinstance(c, dict) and "name" in c and "value" in c
            }
        else:
            return 2, "Input is not a JSON object/array of cookies"

    required = {"auth_token", "ct0"}
    missing = required - set(data.keys())
    if missing:
        return 3, f"Missing required cookie(s): {sorted(missing)}. Need: auth_token, ct0"

    brand = load_brand_profile()
    username = brand["accounts"]["x_twitter"]["username"]
    accounts_dir = Path(__file__).resolve().parents[1] / "accounts"
    accounts_dir.mkdir(parents=True, exist_ok=True)
    dst = accounts_dir / f"x_{username}.cookies.json"

    with dst.open("w") as f:
        json.dump(data, f, indent=2)
    return 0, f"Saved {len(data)} cookies to {dst}"


def cmd_x_import_cookies(args) -> int:
    """Import cookies from a JSON file into accounts/."""
    import json
    from pathlib import Path

    src_path = Path(args.file).expanduser().resolve()
    if not src_path.exists():
        print(f"✗ File not found: {src_path}")
        return 1
    try:
        with src_path.open() as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"✗ Invalid JSON: {e}")
        return 2

    rc, msg = _save_x_cookies(data)
    print(("✓ " if rc == 0 else "✗ ") + msg)
    if rc == 0:
        print("   Run: python -m src.cli x-test")
    return rc


def cmd_x_paste_cookies(args) -> int:
    """Read cookie JSON from stdin (paste directly in terminal)."""
    import json
    import sys

    print("Paste the cookies JSON below, then press Ctrl+D (Mac/Linux) on a new line:\n")
    try:
        raw = sys.stdin.read()
    except KeyboardInterrupt:
        print("\n(cancelled)")
        return 1

    raw = raw.strip()
    if not raw:
        print("✗ No input received")
        return 1

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"✗ Invalid JSON: {e}")
        return 2

    rc, msg = _save_x_cookies(data)
    print(("\n✓ " if rc == 0 else "\n✗ ") + msg)
    if rc == 0:
        print("   Run: python -m src.cli x-test")
    return rc


def cmd_report(args) -> int:
    """Reply-tracking table — shows what OUR accounts replied to which target posts."""
    init_db()

    def trunc(s: str | None, n: int) -> str:
        s = (s or "").replace("\n", " ").strip()
        return s if len(s) <= n else s[: n - 1] + "…"

    def fmt_row(it: dict) -> tuple[str, ...]:
        return (
            f"#{it['id']}",
            it["platform"],
            f"@{it['account_username']}",
            f"@{it.get('parent_author') or '?'}",
            trunc(it.get("parent_post_text"), 60),
            it.get("reply_mode") or "—",
            trunc(it.get("draft_text") or it.get("final_text"), 80),
            it.get("posted_at") or it.get("approved_at") or it.get("drafted_at") or "—",
            trunc(it.get("reply_url"), 50),
        )

    def render_table(title: str, rows: list[dict]) -> None:
        print(f"\n━━━ {title} ({len(rows)}) ━━━")
        if not rows:
            print("  (none)")
            return
        headers = (
            "ID", "Platform", "Our Account", "→ Target", "Target Post",
            "Mode", "Reply Text", "Timestamp", "Reply URL",
        )
        formatted = [headers] + [fmt_row(r) for r in rows]
        widths = [max(len(row[i]) for row in formatted) for i in range(len(headers))]
        widths = [min(w, 80) for w in widths]
        bar = "  ".join("─" * w for w in widths)
        print(bar)
        print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
        print(bar)
        for r in formatted[1:]:
            print("  ".join(c.ljust(w) for c, w in zip(r, widths)))

    posted = list_items(status="posted", limit=200)
    approved = list_items(status="approved", limit=200)
    ready = list_items(status="ready_for_review", limit=200)
    failed = list_items(status="failed", limit=200)

    brand = load_brand_profile()
    caps = brand["operational_caps"]["replies_per_day"]

    print("═══════════════════════════════════════════════════════════════════")
    print("  OpenCraft Social Bot — Reply Tracking Report")
    print("═══════════════════════════════════════════════════════════════════")
    print(f"  Brand:     {brand['brand_name']} — {brand['tagline']}")
    print(f"  Accounts:  @{brand['accounts']['threads']['username']} (threads)  "
          f"·  @{brand['accounts']['x_twitter']['username']} (x)")
    print()
    print("  Daily reply caps:")
    for platform, cap in caps.items():
        n = count_today(platform=platform, status="posted")
        bar = "█" * n + "░" * max(0, cap - n)
        print(f"    {platform:8s} {n}/{cap}  {bar}")

    if args.status in ("all", "posted"):
        render_table("✓ POSTED (live replies)", posted)
    if args.status in ("all", "approved"):
        render_table("● APPROVED (ready to post)", approved)
    if args.status in ("all", "ready_for_review"):
        render_table("◯ READY FOR REVIEW (drafted, awaiting approval)", ready)
    if args.status in ("all", "failed"):
        render_table("✗ FAILED", failed)

    print()
    print("  Commands:")
    print("    Approve:  python -m src.cli approve --id N")
    print("    Post:     python -m src.cli post --id N")
    print("    Skip:     python -m src.cli skip --id N")
    return 0


def cmd_brand_refresh(args) -> int:
    print("→ rebuild brand from Zernio")
    print("  [not implemented yet]")
    print("  Reads ZERNIO_API_KEY from .env, hits /profiles + /accounts + /posts,")
    print("  re-analyzes, writes brand/brand-profile.json (versions old one).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="src.cli", description="OpenCraft social bot")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="Show bot status")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("brand-show", help="Show loaded brand profile summary")
    s.set_defaults(func=cmd_brand_show)

    s = sub.add_parser("scrape", help="Scrape viral posts")
    s.add_argument("--platform", choices=["threads", "x", "all"], default="all")
    s.add_argument("--limit", type=int, default=30)
    s.add_argument(
        "--lax",
        action="store_true",
        help="Disable strict brand filters (engagement + age) for testing the pipeline",
    )
    s.set_defaults(func=cmd_scrape)

    s = sub.add_parser("draft", help="Reports pending drafts — drafting is done by reply-drafter subagent")
    s.add_argument("--limit", type=int, default=5)
    s.add_argument("--platform", choices=["threads", "x", "all"], default="all")
    s.add_argument("--id", type=int, help="(unused here — pass to subagent instead)")
    s.set_defaults(func=cmd_draft)

    s = sub.add_parser("list-scraped", help="(subagent helper) Emit queued items as JSON")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--platform", choices=["threads", "x", "all"], default="all")
    s.add_argument("--id", type=int, help="Filter to specific item id")
    s.set_defaults(func=cmd_list_scraped)

    s = sub.add_parser("save-draft", help="(subagent helper) Persist a draft (text via stdin)")
    s.add_argument("--id", type=int, required=True)
    s.add_argument("--mode", required=True, help="Reply mode: polite_contrarian | concrete_example | etc.")
    s.add_argument("--mark-failed", action="store_true", help="Save stdin text as error message instead")
    s.set_defaults(func=cmd_save_draft)

    s = sub.add_parser("queue", help="Show queue items")
    s.add_argument("--status", default="ready_for_review")
    s.add_argument("--platform", choices=["threads", "x", "all"], default="all")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_queue)

    s = sub.add_parser("approve", help="Approve a queued draft")
    s.add_argument("--id", type=int, required=True)
    s.set_defaults(func=cmd_approve)

    s = sub.add_parser("skip", help="Skip a queued draft")
    s.add_argument("--id", type=int, required=True)
    s.add_argument("--reason", default="user_skipped")
    s.set_defaults(func=cmd_skip)

    s = sub.add_parser("post", help="Publish approved reply")
    s.add_argument("--id", type=int)
    s.add_argument("--all-approved", action="store_true")
    s.set_defaults(func=cmd_post)

    s = sub.add_parser("scrapers", help="Diagnostics: cookies, last run, queue depth per platform")
    s.add_argument("--probe", action="store_true", help="Live Playwright probe of X session")
    s.set_defaults(func=cmd_scrapers)

    s = sub.add_parser("x-login", help="Open visible browser → log in → auto-save cookies")
    s.set_defaults(func=cmd_x_login)

    s = sub.add_parser("x-test", help="Verify X cookies (must be imported first)")
    s.set_defaults(func=cmd_x_test)

    s = sub.add_parser(
        "threads-login",
        help="Open visible browser → log in to Threads → auto-save cookies",
    )
    s.set_defaults(func=cmd_threads_login)

    s = sub.add_parser(
        "threads-test",
        help="Verify saved Threads cookies still produce a logged-in session",
    )
    s.set_defaults(func=cmd_threads_test)

    s = sub.add_parser("x-import-cookies", help="Import X cookies JSON from a file (alt to x-login)")
    s.add_argument("--file", required=True, help="Path to cookies JSON file")
    s.set_defaults(func=cmd_x_import_cookies)

    s = sub.add_parser("x-paste-cookies", help="Paste X cookies JSON directly via stdin (no file needed)")
    s.set_defaults(func=cmd_x_paste_cookies)

    s = sub.add_parser("report", help="Reply-tracking table: who we replied to, by status")
    s.add_argument(
        "--status",
        choices=["all", "posted", "approved", "ready_for_review", "failed"],
        default="all",
        help="Filter to one status section",
    )
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("brand-refresh", help="Re-build brand profile from Zernio")
    s.set_defaults(func=cmd_brand_refresh)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
