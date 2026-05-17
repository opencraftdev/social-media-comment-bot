# 01 — twikit Overview

> https://github.com/d60/twikit

## What twikit Is

A Python library that talks to X's **internal GraphQL API** (the same one the web client uses) by hijacking your login session. No developer account, no API keys, no payment.

## What It Can Do

| Capability | Method | Notes |
|------------|--------|-------|
| Login with credentials | `Client.login()` | Supports 2FA/TOTP |
| Persist session | `cookies_file=...` | Avoid re-login |
| Post tweet | `client.create_tweet()` | Text + media |
| **Reply to any tweet** | `create_tweet(reply_to=...)` | **Core feature** |
| Quote tweet | `create_tweet(attachment_url=...)` | |
| Get tweet by ID | `get_tweet_by_id()` | |
| Delete tweet | `delete_tweet()` | |
| **Search tweets** | `search_tweet(q, product)` | Top / Latest / Media |
| **Get trending** | `get_trends(category)` | trending / news / sports / etc. |
| Like / unlike | `favorite_tweet()` / `unfavorite_tweet()` | |
| Retweet / un-RT | `retweet()` / `delete_retweet()` | |
| Follow / unfollow | `follow_user()` / `unfollow_user()` | |
| Get user info | `get_user_by_screen_name()` | |
| Get user tweets | `get_user_tweets()` | |
| Send DM | `send_dm()` | |
| Upload media | `upload_media()` | Image/video → media_id |
| Block / mute | `block_user()` / `mute_user()` | |
| Get followers/following | `get_user_followers()` / `following()` | |

## What It Can't Do (Easily)

- ❌ Posts > 280 chars without X Premium account
- ❌ Live streams
- ❌ Some Premium-only features (richtext, edit tweet)
- ❌ Guaranteed reliability — X breaks internal API occasionally → wait for twikit update

## Risk Profile

| Risk | Severity | Mitigation |
|------|----------|------------|
| Account ban | 🟡 Medium | Hygiene rules ([06-rate-limits-bans.md](./06-rate-limits-bans.md)) |
| Internal API breaks | 🟡 Medium | Pin twikit version, watch for releases |
| Legal (ToS) | 🟢 Low | X has not pursued individuals using libraries like this |
| Captcha / login challenge | 🟡 Medium | Use cookies (skip re-login), TOTP, residential IP |

## Architecture

```
Your code  →  twikit Client  →  X GraphQL endpoints
                ↓
           cookies.json (session)
```

All operations are `async/await`. Single client instance per account.

## Versioning

- Active development as of 2026
- Pin version in `requirements.txt`: `twikit==2.x.x`
- X changes internal API ~every few months — expect to update twikit version
