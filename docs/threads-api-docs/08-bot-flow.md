# 08 — End-to-End Bot Flow (Manual URL → Auto Reply)

> **Implementation blueprint.** No Meta app review needed.

## High-Level Pipeline

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  USER PASTES    │ →  │  AI DRAFT       │ →  │  AUTO REPLY     │
│  Threads URL    │    │  Claude / GPT   │    │  /threads +     │
│  (dashboard)    │    │  (external)     │    │  /threads_publish│
└─────────────────┘    └─────────────────┘    └─────────────────┘
       │                                              │
       └─── extract post ID → dedup → approval ──────┘
```

## Detailed Pseudocode

```python
# Config
ACCOUNTS = load("accounts/*.json")        # 6 long-lived tokens
DAILY_REPLY_CAP = 8                       # per account
MIN_DELAY = 60                            # seconds between actions
MAX_DELAY = 300

# Endpoint hit by dashboard / iOS shortcut / bookmarklet
async def queue_post(url, target_account_username, post_text=None):

    # 1) Extract post ID from URL
    parsed = parse_threads_url(url)        # see 04-manual-post-id-flow.md
    if not parsed:
        return error("Invalid Threads URL")

    # 2) Resolve account
    account = accounts[target_account_username]

    # 3) Token health
    if account.token_expires_in_days() < 7:
        account.refresh_token()             # see 02-authentication.md

    # 4) Quota check
    quota = GET /{account.user_id}/threads_publishing_limit
    if quota.reply_quota_usage >= DAILY_REPLY_CAP:
        return error("Daily cap reached")

    # 5) Dedup
    if db.already_replied(account, parsed["post_id"]):
        return error("Already replied to this post")

    # 6) Fetch post text if not provided (scrape OG tag)
    if not post_text:
        post_text = await fetch_post_text(url)

    # 7) AI draft
    draft = await claude.generate_comment(
        post_text=post_text,
        account_persona=account.persona,
        max_length=500
    )

    # 8) Queue for human approval (semi-auto)
    queue_id = db.queue_for_review({
        account: account.username,
        post_id: parsed["post_id"],
        post_url: parsed["url"],
        post_text: post_text,
        draft: draft,
    })

    return { queue_id, draft }


# Called when user clicks "Approve" on dashboard
async def approve_and_post(queue_id, final_text):

    item = db.get_queued(queue_id)
    account = accounts[item.account]

    # Step 1 — Create reply container
    creation = POST /{account.user_id}/threads
        body: {
            media_type: "TEXT",
            text: final_text,
            reply_to_id: item.post_id,
            access_token: account.token
        }

    sleep(2)   # tiny wait for container

    # Step 2 — Publish
    published = POST /{account.user_id}/threads_publish
        body: {
            creation_id: creation.id,
            access_token: account.token
        }

    # Record
    db.mark_posted(queue_id, reply_media_id=published.id)

    # Anti-bot pacing
    sleep(random(MIN_DELAY, MAX_DELAY))

    return published.id
```

## Approval Dashboard

```
┌────────────────────────────────────────────────────┐
│ Account: @your_handle                              │
│ Replying to: @someuser                             │
│ Their post: "AI agents will eat SaaS by 2027…"     │
│ URL: https://threads.net/@someuser/post/CxYz123    │
│                                                    │
│ AI draft:                                          │
│ ┌────────────────────────────────────────────────┐ │
│ │ Eating SaaS implies replacing UI — but agents  │ │
│ │ need UI to expose capability boundaries.        │ │
│ └────────────────────────────────────────────────┘ │
│                                                    │
│ [ ✓ Approve & Post ]  [ ✎ Edit ]  [ ✕ Skip ]        │
└────────────────────────────────────────────────────┘
```

## Three Ways User Adds URLs to Queue

| Method | UX |
|--------|----|
| **Web dashboard** | Paste URL + select account → click Add |
| **iOS Share Sheet** | In Threads app: Share → "Send to Bot" → done |
| **Chrome bookmarklet** | One click on a Threads post page |

See [04-manual-post-id-flow.md](./04-manual-post-id-flow.md) for setup.

## Local DB Schema

```sql
CREATE TABLE replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_username TEXT NOT NULL,
    parent_post_id TEXT NOT NULL,
    parent_post_url TEXT,
    parent_post_text TEXT,
    draft_text TEXT,
    final_text TEXT,
    reply_media_id TEXT,
    status TEXT NOT NULL,         -- queued | approved | posted | failed | skipped
    queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    posted_at TIMESTAMP,
    UNIQUE(account_username, parent_post_id)
);

CREATE TABLE accounts (
    username TEXT PRIMARY KEY,
    user_id TEXT,
    access_token TEXT,
    token_expires_at TIMESTAMP,
    persona TEXT,                  -- AI prompt context
    daily_reply_cap INTEGER DEFAULT 8
);
```

## Files to Reference

| Step | Doc |
|------|-----|
| OAuth + token refresh | [02-authentication.md](./02-authentication.md) |
| URL → post ID + paste flow | [04-manual-post-id-flow.md](./04-manual-post-id-flow.md) |
| Reply create + publish | [05-create-reply.md](./05-create-reply.md) |
| Dedup (local DB primary) | [06-fetch-replies.md](./06-fetch-replies.md) |
| Quota check | [07-rate-limits.md](./07-rate-limits.md) |

## Pre-Build Checklist

- [ ] Meta Developer App created with **Threads use case**
- [ ] OAuth redirect URI configured (HTTPS)
- [ ] 6 Threads accounts ready
- [ ] 6 long-lived tokens generated (scope: `threads_basic,threads_content_publish`)
- [ ] AI provider chosen (Claude / Gemini / OpenAI)
- [ ] Dashboard UI built (paste URL → approve)
- [ ] iOS Shortcut / bookmarklet created (optional power-user)
- [ ] Hosting decision (local cron / VPS / serverless)

## NOT in Scope (Skipped — No Approval Needed)

- ❌ Automatic trending discovery via `keyword_search`
- ❌ Reading public replies via `threads_read_replies`
- ❌ Insights / analytics
- ❌ Reply moderation
