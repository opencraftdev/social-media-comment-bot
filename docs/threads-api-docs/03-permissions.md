# 03 — Permissions / Scopes

## What We Need (Day 1 Ready, No App Review)

```
threads_basic,threads_content_publish
```

Both are **auto-approved** instantly. No demo video, no Meta review, no waiting.

## All Threads API Scopes Reference

| Scope | Purpose | App Review? | Our Bot Uses? |
|-------|---------|-------------|----------------|
| `threads_basic` | Read profile + own posts | ❌ Auto | ✅ **Yes** |
| `threads_content_publish` | Create posts and replies | ❌ Auto | ✅ **Yes** |
| `threads_delete` | Delete own posts | ❌ Auto | ⚠️ Optional |
| `threads_manage_replies` | Hide/unhide, approve replies | ✅ Review | ⏸️ Skipped |
| `threads_read_replies` | Read replies on posts | ✅ Review | ⏸️ Skipped (use local DB) |
| `threads_keyword_search` | Search public posts by keyword | ✅ Review | ⏸️ Skipped (manual URL paste) |
| `threads_manage_insights` | Read insights | ✅ Review | ⏸️ Skipped |
| `threads_business_discovery` | Discover business profiles | ✅ Review | ❌ Not needed |
| `threads_location_tagging` | Tag locations | ✅ Review | ❌ Not needed |

## Why We Skip the Review-Gated Scopes

| Skipped Scope | What We Do Instead |
|---------------|--------------------|
| `threads_keyword_search` | User pastes Threads post URLs manually → bot extracts ID → bot replies. See [04-manual-post-id-flow.md](./04-manual-post-id-flow.md). |
| `threads_read_replies` | We track our own replies in a local SQLite DB for dedup. No API call needed. |
| `threads_manage_replies` | We're commenting on others' posts — not moderating our own. |
| `threads_manage_insights` | Analytics are nice-to-have, not core. Can add later via review. |

## OAuth Scope String for Our Bot

```
https://threads.net/oauth/authorize
  ?client_id={THREADS_APP_ID}
  &redirect_uri={REDIRECT_URI}
  &scope=threads_basic,threads_content_publish
  &response_type=code
```

That's it. Single line, two scopes, no approval gate.

## Future Upgrade Path

If/when we want **automatic trending discovery** instead of manual URL paste:

1. Build a public website + privacy policy
2. Verify Meta Business Manager
3. Record a demo video framing as "social listening tool"
4. Submit `threads_keyword_search` for review (2-4 weeks)
5. Add scope to OAuth string
6. Plug auto-discovery into the existing queue endpoint

**Until then, the bot is fully functional with just the two auto-approved scopes.**
