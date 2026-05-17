# X (Twitter) twikit Docs — Bot Use Case Index

> Source: https://github.com/d60/twikit
> Docs: https://twikit.readthedocs.io/en/latest/
> Curated for: **Auto-comment bot on trending X posts (5-6 accounts/day, semi-automated)**

## Why twikit (Not Official X API)

| | Official X API | twikit |
|---|----------------|--------|
| Cost | $200-$5,000/mo | **Free** |
| Developer account | Required | Not needed |
| Reply to anyone | ✅ | ✅ |
| Get trending topics | Pro tier only | ✅ Free |
| Search tweets | Limited free | ✅ Free |
| ToS compliant | ✅ | ❌ (unofficial) |
| Ban risk | Low | 🟡 Medium (manageable) |

twikit mimics the X web client by using the internal GraphQL API. **No API keys needed** — uses your account credentials (cookies).

## Bot Flow Mapped to twikit

```
1. Login each of 5-6 accounts (save cookies)  → 03-authentication.md
2. Get trending topics                         → 04-trending-search.md
3. Search tweets for each trend (Top/Latest)   → 04-trending-search.md
4. Filter tweets (engagement, recency, dedup)  → 04-trending-search.md
5. Generate AI comment (external — Claude)     → (not in this doc)
6. create_tweet(text=..., reply_to=tweet_id)   → 05-reply-tweet.md
7. Sleep + rotate accounts                     → 06-rate-limits-bans.md
```

## Files

| File | What's Inside |
|------|---------------|
| [01-overview.md](./01-overview.md) | What twikit supports + risk profile |
| [02-installation-setup.md](./02-installation-setup.md) | pip install, Python version, deps |
| [03-authentication.md](./03-authentication.md) | Login, 2FA/TOTP, cookies, multi-account |
| [04-trending-search.md](./04-trending-search.md) | `get_trends()` + `search_tweet()` |
| [05-reply-tweet.md](./05-reply-tweet.md) | `create_tweet(reply_to=...)` for replies |
| [06-rate-limits-bans.md](./06-rate-limits-bans.md) | Anti-ban hygiene, proxies, account warming |
| [07-bot-flow.md](./07-bot-flow.md) | End-to-end pseudocode for X bot |

## Critical Capabilities for Our Bot

| Need | twikit Method | Status |
|------|--------------|--------|
| Login (no API key) | `Client.login()` | ✅ |
| Persist session | `cookies_file=...` / `save_cookies()` | ✅ |
| Get trending | `client.get_trends('trending')` | ✅ |
| Search tweets | `client.search_tweet(q, 'Top')` | ✅ |
| **Reply to any tweet** | `client.create_tweet(text, reply_to=tweet_id)` | ✅ |
| Like | `client.favorite_tweet(id)` | ✅ |
| Retweet | `client.retweet(id)` | ✅ |
| Get tweet by ID | `client.get_tweet_by_id(id)` | ✅ |

## Quickstart Snippet

```python
import asyncio
from twikit import Client

async def main():
    client = Client('en-US')
    await client.login(
        auth_info_1='username',
        auth_info_2='email@example.com',
        password='password',
        cookies_file='cookies.json'
    )

    trends = await client.get_trends('trending')
    for t in trends[:5]:
        print(t.name)

        tweets = await client.search_tweet(t.name, 'Top')
        target = tweets[0]

        await client.create_tweet(
            text='Great take!',
            reply_to=target.id
        )

asyncio.run(main())
```

## Risk Disclosure

⚠️ twikit is **unofficial**. X can detect and ban automated behavior. Mitigations in [06-rate-limits-bans.md](./06-rate-limits-bans.md):

- Save cookies (don't re-login every run)
- Random delays (60-300s between actions)
- Max 5-10 replies/account/day
- Residential proxies (one per account)
- AI-varied comments (not templates)
- Warm up new accounts (low volume for 2 weeks)
