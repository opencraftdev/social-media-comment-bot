# 04 — Manual Post ID Flow (No Meta Approval Needed)

> **This is the trending-discovery replacement.** Instead of `threads_keyword_search` (which needs Meta app review), the user provides post URLs/IDs manually. Bot handles everything else automatically.

## Why This Approach

| | Keyword Search | Manual URL Flow |
|---|----------------|------------------|
| Meta approval | Required (2-4 weeks) | **Not needed** |
| Build start | Blocked on review | **Day 1** |
| Trending discovery | Automatic | Manual (you paste URL) |
| Reply posting | Automatic | Automatic |
| Risk of rejection | Medium | None |

You sacrifice **trending discovery automation**, you keep **everything else automated** — auth, dedup, AI drafting, posting, rate limits, multi-account.

## How a User Adds Posts to the Queue

### Threads Post URL Format

```
https://www.threads.net/@username/post/CxYz123AbC
                          │           │
                       handle    shortcode (base64-ish)
```

### Three Ways to Capture the URL

| Method | UX |
|--------|----|
| **Paste URL in dashboard** | Web form: paste → click Add → AI drafts → approve |
| **Share Sheet (mobile)** | iOS Shortcut / Android Share → POST URL to your bot's webhook |
| **Bookmarklet** | One-click "Send to Bot" button in browser |

## Extracting Post ID from URL

### Option 1 — Shortcode Decode (Fast, Offline)

Threads uses Instagram-style base64 shortcodes. Decode to numeric ID:

```python
def shortcode_to_id(shortcode: str) -> str:
    alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
    post_id = 0
    for char in shortcode:
        post_id = post_id * 64 + alphabet.index(char)
    return str(post_id)

import re

def parse_threads_url(url: str) -> dict | None:
    match = re.match(r'https?://(?:www\.)?threads\.net/@([\w.]+)/post/([\w-]+)', url)
    if not match:
        return None
    username, shortcode = match.groups()
    return {
        "username": username,
        "shortcode": shortcode,
        "post_id": shortcode_to_id(shortcode),
        "url": url,
    }
```

Example:

```python
>>> parse_threads_url('https://www.threads.net/@someuser/post/CxYz123AbC')
{
    'username': 'someuser',
    'shortcode': 'CxYz123AbC',
    'post_id': '17841400000000001',
    'url': 'https://www.threads.net/@someuser/post/CxYz123AbC'
}
```

### Option 2 — Fetch HTML and Parse (Reliable Fallback)

If shortcode decoding fails on edge cases, fetch the URL and extract the canonical ID from the OG meta tags:

```python
import httpx, re

async def fetch_post_id(url: str) -> str | None:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    # Look for canonical post id in HTML
    m = re.search(r'"pk":"(\d+)"', r.text) or re.search(r'/media/(\d+)/', r.text)
    return m.group(1) if m else None
```

> ⚠️ Scraping is fragile. Use as fallback, not primary.

## Fetching Post Text (For AI Context)

The AI comment generator needs the post text. Two ways:

### A — User Pastes Text Too

Simplest. Dashboard has both fields:

```
URL:  [https://www.threads.net/@... ]
Text: [paste post text for AI context...]
```

### B — Scrape OG Tags (Optional)

```python
async def fetch_post_text(url: str) -> str | None:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    m = re.search(r'<meta property="og:description" content="([^"]+)"', r.text)
    return m.group(1) if m else None
```

## Bot Endpoint for Adding Posts

```python
# FastAPI / Flask endpoint
from fastapi import FastAPI
app = FastAPI()

@app.post("/api/queue")
async def queue_post(payload: dict):
    """
    body: {
        "url": "https://www.threads.net/@user/post/XXX",
        "text": "...",                  # optional, will scrape if missing
        "target_account": "acc_1"       # which of your accounts replies
    }
    """
    parsed = parse_threads_url(payload["url"])
    if not parsed:
        return {"error": "invalid URL"}

    text = payload.get("text") or await fetch_post_text(payload["url"])

    # Dedup
    if await db.has_replied(payload["target_account"], parsed["post_id"]):
        return {"error": "already replied"}

    # AI draft
    draft = await ai.generate_comment(
        post_text=text,
        persona=accounts[payload["target_account"]].persona
    )

    queue_id = await db.queue_for_review(
        account=payload["target_account"],
        post_id=parsed["post_id"],
        post_url=parsed["url"],
        post_text=text,
        draft=draft,
    )
    return {"queue_id": queue_id, "draft": draft}
```

## iOS Share Sheet Shortcut (Power User)

Create iOS Shortcut:

```
1. "When sharing a URL from Threads app"
2. Get URL from input
3. Get Contents of URL: POST {your-bot-host}/api/queue
   Body (JSON): { "url": <input>, "target_account": "acc_1" }
4. Show notification: "Queued for review ✓"
```

Now: open Threads → see trending → tap Share → "Send to Bot" → it's queued.

## Approval Dashboard (Same as Before)

```
┌──────────────────────────────────────────────────────────┐
│ Account: @your_handle                                    │
│ Target URL: https://www.threads.net/@user/post/XXX       │
│ Their post: "AI agents will eat SaaS by 2027…"           │
│                                                          │
│ AI draft (variant: contrarian):                          │
│ "Eating SaaS implies replacing UI — but agents need…"   │
│                                                          │
│ [ ✓ Approve & Post ]  [ ✎ Edit ]  [ ✕ Skip ]              │
└──────────────────────────────────────────────────────────┘
```

On approve → calls reply API ([05-create-reply.md](./05-create-reply.md)).

## What This Flow Avoids

- ❌ No `threads_keyword_search` permission
- ❌ No Meta app review submission
- ❌ No risk of rejection
- ❌ No 2-4 week wait

## What You Trade Off

- ⚠️ Trending discovery is **your job** (browse + paste)
- ⚠️ Mitigations: iOS Share Shortcut, Chrome bookmarklet, scheduled "trending review" sessions

## Future Upgrade Path

When you're ready, you can submit `threads_keyword_search` for app review and add an **automatic discovery** module on top of this flow without rewriting anything — the queue endpoint stays the same, you just add a second producer that auto-fills it.
