# 01 — Threads API Overview

> Source: https://developers.facebook.com/docs/threads/

## What We Use (No App Review Needed)

| Capability | Supported | Endpoint / Notes |
|------------|-----------|------------------|
| Post text/image/video to your own account | ✅ | `POST /{user-id}/threads` + `_publish` |
| **Reply to ANY public post** | ✅ | `POST /{user-id}/threads` with `reply_to_id` |
| Quote/repost public posts | ✅ | `quote_post_id` / `repost_id` params |
| Get insights (impressions, likes) | ✅ | `GET /{media-id}/insights` |

## What We're SKIPPING (Avoids App Review)

| Feature | Reason Skipped | Workaround |
|---------|---------------|------------|
| `GET /keyword_search` | Needs `threads_keyword_search` review | Manual URL paste — see [04-manual-post-id-flow.md](./04-manual-post-id-flow.md) |
| `GET /{media-id}/replies` (others' posts) | Needs `threads_read_replies` review | Use local DB for dedup |
| Insights / analytics | Needs `threads_manage_insights` review | Not core to bot — defer |

## What's NOT Supported (Platform-Level Blocks)

- ❌ Cannot get global "trending topics" endpoint
- ❌ Cannot DM users
- ❌ Cannot follow/unfollow programmatically
- ❌ Cannot like posts (no like endpoint)
- ❌ Cannot get full reply trees on arbitrary posts

## Base URL

```
https://graph.threads.net/v1.0
```

## Two-Step Publishing Pattern

All posts (including replies) use a 2-step flow:

```
Step 1: POST /{user-id}/threads
        → returns { "id": "<creation_id>" }

Step 2: POST /{user-id}/threads_publish
        body: { creation_id: "<creation_id>" }
        → returns { "id": "<media_id>" }
```

Meta recommends polling container status max **once per minute, not more than 5 minutes**.

## Authentication Summary

- OAuth 2.0 with Threads-specific app credentials
- Bearer token in `Authorization` header OR `access_token` query param
- Token lifecycle: code → 1h short-lived → 60-day long-lived → refresh
