# Threads API Docs — Bot Use Case Index

> Source: https://developers.facebook.com/docs/threads/
> Curated for: **Semi-auto comment bot on Threads (5-6 accounts/day, manual URL input → automated reply)**

## Approach — No Meta App Review Needed

We use **only auto-approved permissions** (`threads_basic` + `threads_content_publish`).
Trending discovery is **manual** (you paste post URLs) — replying is **automatic**.

## Bot Flow Mapped to API

```
1. Authenticate each of 5-6 accounts          → 02-authentication.md
2. User pastes Threads post URL into dashboard → 04-manual-post-id-flow.md
3. Bot extracts post ID from URL               → 04-manual-post-id-flow.md
4. AI generates contextual comment (external)  → (not in this doc)
5. User approves draft (semi-auto)             → 04-manual-post-id-flow.md
6. Create reply container with reply_to_id     → 05-create-reply.md
7. Publish reply                               → 05-create-reply.md
8. Track quota usage                           → 07-rate-limits.md
```

## Files

| File | What's Inside | Why It Matters for Us |
|------|---------------|------------------------|
| [01-overview.md](./01-overview.md) | What official API supports vs blocks | Confirms commenting on others' posts is possible |
| [02-authentication.md](./02-authentication.md) | OAuth setup, token lifecycle | Need 5-6 long-lived tokens (one per account) |
| [03-permissions.md](./03-permissions.md) | All scopes — minimal set, no review needed | Just `threads_basic` + `threads_content_publish` |
| [04-manual-post-id-flow.md](./04-manual-post-id-flow.md) | URL→ID conversion, paste flow, share shortcuts | Replaces auto-trending (no Meta approval needed) |
| [05-create-reply.md](./05-create-reply.md) | Create reply to ANY public post via `reply_to_id` | Core "auto-comment" feature |
| [06-fetch-replies.md](./06-fetch-replies.md) | Read existing replies on a post | Optional — avoid duplicate replies |
| [07-rate-limits.md](./07-rate-limits.md) | Quotas: 1,000 replies/24h | Plan multi-account scheduling |
| [08-bot-flow.md](./08-bot-flow.md) | End-to-end pseudocode for the bot | Implementation blueprint |

## Critical Permissions Checklist

| Scope | Auto-approved? | Needed For |
|-------|----------------|------------|
| `threads_basic` | ✅ Yes | All calls |
| `threads_content_publish` | ✅ Yes | Posting replies |
| ~~`threads_keyword_search`~~ | ❌ App Review | ⏸️ **SKIPPED** — manual URL paste instead |
| ~~`threads_read_replies`~~ | ❌ App Review | ⏸️ Optional — use local DB for dedup |
| ~~`threads_manage_replies`~~ | ❌ App Review | ⏸️ Optional |

**✅ Day 1 ready** — no Meta app review required.

## Base URL

```
https://graph.threads.net/v1.0
```

## Token Lifecycle Summary

```
Authorization Code  →  Short-lived token (1 hour)
                    →  Long-lived token (60 days)
                    →  Refresh before expiry (loop)
```
