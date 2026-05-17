# 06 — Rate Limits & Anti-Ban Hygiene

> twikit talks to X's **internal** API → no official quotas published.
> All numbers below are **operational guidance** distilled from community experience.

## Safe Rates per Account (Soft Limits)

| Action | Safe Rate | Hard Limit (approx.) |
|--------|-----------|----------------------|
| Login | 1 per session | 3-5/day before challenge |
| `get_trends` | 1 / 10-30 min | ~30/day |
| `search_tweet` | 1 / 20-60s | ~300/day |
| `create_tweet` (reply) | **1 / 5-30 min** | **~50/day max, 5-10 recommended** |
| `favorite_tweet` (like) | 1 / 10-60s | ~200/day |
| `retweet` | 1 / 5-15 min | ~100/day |
| `follow_user` | 1 / hour | ~50/day |

## Account Health Score (Heuristic)

X computes an internal "automation score". Behaviors that lower it:

| Behavior | Score Impact |
|----------|--------------|
| New account (<3 months) | 🔴 Heavy |
| <500 followers | 🟡 Med |
| Posting from datacenter IP | 🔴 Heavy |
| Same User-Agent across sessions | 🟡 Med |
| Action burstiness (8 actions in 2 min) | 🔴 Heavy |
| Reply-to-original ratio < 1:5 | 🔴 Heavy |
| Replies to verified/large accounts only | 🟡 Med |
| Posting only during one timezone window | 🟢 Low |

## Anti-Ban Hygiene Rules

### 1. **Save Cookies, Don't Re-Login**

```python
# BAD: re-logs every run
await client.login(...)

# GOOD: loads session
client.load_cookies('acc.cookies.json')
```

### 2. **Random Delays Between Actions**

```python
import random, asyncio

async def safe_sleep():
    await asyncio.sleep(random.uniform(60, 300))   # 1-5 min
```

### 3. **Daily Caps per Account**

```python
DAILY_CAPS = {
    'replies': 8,
    'likes': 30,
    'searches': 50,
}
```

### 4. **Stagger Accounts Across the Day**

Bad: all 6 accounts run 9-10am.

Good:

| Account | Active Window |
|---------|---------------|
| acc_1 | 07:00-11:00 |
| acc_2 | 10:00-14:00 |
| acc_3 | 13:00-17:00 |
| acc_4 | 16:00-20:00 |
| acc_5 | 19:00-23:00 |
| acc_6 | random off-peak |

### 5. **Residential Proxies (One per Account)**

Datacenter IPs are flagged. Use:
- IPRoyal / Bright Data / Smartproxy (residential pools)
- Geo-match proxy to account's claimed location
- One sticky session per account (don't rotate mid-session)

### 6. **Warm Up New Accounts**

| Week | Daily Reply Cap | Other Actions |
|------|-----------------|---------------|
| 1 | 1-2 | Browse, like 5-10 |
| 2 | 3-4 | Like 15-20, retweet 1-2 |
| 3 | 5-6 | Add follows, post 1 original/day |
| 4+ | 8-10 | Full operation |

### 7. **Vary Comment Style**

Don't let AI fall into patterns. Rotate prompts:

```python
PROMPT_VARIANTS = [
    "Reply with a contrarian take in 1-2 sentences",
    "Reply with a question that adds nuance",
    "Reply with a related data point or example",
    "Reply with a personal anecdote",
    "Reply with a counter-example",
]
```

### 8. **Mix Action Types**

A pure-replies account looks like a spam bot. Mix:

| Action | Daily % |
|--------|---------|
| Replies (our goal) | 30% |
| Likes | 40% |
| Original posts | 10% |
| Browsing (sleep + idle) | 20% |

## Detecting You've Been Flagged

| Symptom | Severity |
|---------|----------|
| `TooManyRequests` after few actions | 🟡 Soft rate limit — wait 30 min |
| Replies not visible to non-followers | 🟠 Shadowban — slow down 1 week |
| `Forbidden 326` on login | 🔴 Account locked — manual login + verify phone/email |
| Account suspended | 🔴 Game over — appeal or rotate |

## Backoff Strategy

```python
import asyncio
from twikit.errors import TooManyRequests

async def with_backoff(fn, *args, **kwargs):
    for attempt in range(3):
        try:
            return await fn(*args, **kwargs)
        except TooManyRequests:
            wait = 900 * (attempt + 1)   # 15, 30, 45 min
            await asyncio.sleep(wait)
    raise RuntimeError("Backoff exhausted")
```

## Hard Don'ts

- ❌ Don't post identical text across accounts
- ❌ Don't reply with only emojis or only links
- ❌ Don't follow/unfollow loops
- ❌ Don't reply to ads / promoted posts
- ❌ Don't run 24/7 — give each account an 8h "sleep" window
- ❌ Don't log in from new IP without prior browser session warmup

## Realistic Operation Math

| Setting | Value |
|---------|-------|
| Accounts | 6 |
| Replies / account / day | 5-8 |
| Total replies / day | **30-48** |
| Searches / account / day | ~15 |
| Trending fetches / account / day | ~4 |
| Expected ban rate (with hygiene) | 1 account / 2-3 months |

Budget 1-2 burner accounts as replacements.
