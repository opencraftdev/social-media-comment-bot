# 07 — End-to-End X Bot Flow

> **Implementation blueprint mapping each step to a twikit call.**

## Pipeline

```
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ TRENDING        │ → │  AI DRAFT       │ → │  REPLY POST     │
│ get_trends()    │   │  Claude         │   │  create_tweet(  │
│ search_tweet()  │   │  (external)     │   │   reply_to=...) │
└─────────────────┘   └─────────────────┘   └─────────────────┘
        │                                          │
        └── dedup, filter ──→ (approval queue) ────┘
```

## Daily Pseudocode

```python
import asyncio, random
from datetime import datetime, timedelta

CONFIG = {
    "accounts": load_accounts(),         # 6 Account objects
    "min_delay": 60,
    "max_delay": 300,
    "daily_reply_cap": 8,
    "max_tweet_age_hours": 6,
    "min_target_likes": 50,
    "min_target_followers": 1000,
    "semi_auto": True,                   # human approval before posting
}

async def run_account(account):
    client = await account_manager.get_client(account.username)

    # 1) Quota check (local DB)
    if await db.replies_today(account.username) >= account.daily_reply_cap:
        return

    # 2) Find candidates
    trends = await client.get_trends('trending', count=20)
    trend_names = [t.name for t in trends]

    candidates = []
    for query in account.keywords + trend_names[:5]:
        try:
            results = await client.search_tweet(
                f'{query} lang:en -is:reply min_faves:{CONFIG["min_target_likes"]}',
                'Top',
                count=15
            )
        except TooManyRequests:
            await asyncio.sleep(900)
            continue

        for tweet in results:
            if tweet.user.followers_count < CONFIG["min_target_followers"]:
                continue
            if (datetime.now() - tweet.created_at) > timedelta(hours=CONFIG["max_tweet_age_hours"]):
                continue
            if await db.has_replied(account.username, tweet.id):
                continue
            if await any_account_replied(tweet.id):    # don't cluster-reply
                continue
            candidates.append(tweet)

        await asyncio.sleep(random.uniform(20, 60))

    # 3) Rank by engagement
    candidates.sort(
        key=lambda t: t.favorite_count + t.reply_count * 2,
        reverse=True
    )

    needed = CONFIG["daily_reply_cap"] - await db.replies_today(account.username)
    top_picks = candidates[:needed]

    # 4) For each pick → AI → (review) → post
    for target in top_picks:
        draft = await ai.generate_comment(
            tweet_text=target.text,
            persona=account.persona,
            variant=random.choice(PROMPT_VARIANTS),
            max_chars=270
        )

        if CONFIG["semi_auto"]:
            await db.queue_for_review(account.username, target, draft)
            continue

        # Fully auto
        try:
            reply = await client.create_tweet(
                text=draft,
                reply_to=target.id
            )
            await db.record_reply(account.username, target.id, reply.id, draft)
        except Exception as e:
            await db.log_failure(account.username, target.id, str(e))

        # Random delay between replies
        await asyncio.sleep(random.uniform(CONFIG["min_delay"], CONFIG["max_delay"]))

async def main():
    # Stagger account start times
    tasks = []
    for i, account in enumerate(CONFIG["accounts"]):
        delay = i * 1800   # 30 min between account starts
        tasks.append(asyncio.create_task(_delayed_run(account, delay)))
    await asyncio.gather(*tasks)

async def _delayed_run(account, delay):
    await asyncio.sleep(delay)
    await run_account(account)

asyncio.run(main())
```

## Approval Queue (Semi-Auto Mode)

Simple HTML dashboard reads queued items from DB:

```
┌────────────────────────────────────────────────────────────┐
│ Account: @your_bot_1                                       │
│ Target: @elonmusk · 12 min ago · 4.2K ♥ · 800 💬            │
│ Tweet: "AI agents are overrated. Here's why..."            │
│                                                            │
│ AI draft (variant: contrarian take):                       │
│ "Agent latency is down 10x in 6 months. The 'overrated'   │
│  label assumed 2024 perf — different game now."           │
│                                                            │
│ [ ✓ Approve & Post ]  [ ✎ Edit ]  [ ✕ Skip ]                │
└────────────────────────────────────────────────────────────┘
```

On approve → calls `create_tweet(text=edited_text, reply_to=target.id)`.

## Local DB Schema (SQLite)

```sql
CREATE TABLE replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_username TEXT NOT NULL,
    parent_tweet_id TEXT NOT NULL,
    parent_tweet_url TEXT,
    parent_tweet_text TEXT,
    parent_author TEXT,
    parent_likes INTEGER,
    reply_id TEXT,
    reply_text TEXT,
    status TEXT NOT NULL,      -- queued | approved | posted | failed | skipped
    error TEXT,
    queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    posted_at TIMESTAMP,
    UNIQUE(account_username, parent_tweet_id)
);

CREATE INDEX idx_replies_account_date ON replies(account_username, posted_at);
CREATE INDEX idx_replies_status ON replies(status);

CREATE TABLE accounts (
    username TEXT PRIMARY KEY,
    email TEXT,
    persona TEXT,             -- AI persona prompt
    keywords TEXT,            -- JSON array
    daily_reply_cap INTEGER DEFAULT 8,
    proxy TEXT,
    active BOOLEAN DEFAULT 1,
    last_active TIMESTAMP
);
```

## Helpful Queries

```sql
-- Today's replies per account
SELECT account_username, COUNT(*) FROM replies
WHERE date(posted_at) = date('now') AND status = 'posted'
GROUP BY account_username;

-- Failed replies in last 24h (review for ban signals)
SELECT account_username, parent_tweet_id, error
FROM replies
WHERE status = 'failed' AND posted_at > datetime('now', '-1 day');

-- Pending approvals
SELECT * FROM replies WHERE status = 'queued' ORDER BY queued_at;
```

## Cron Setup

```cron
# 6 staggered runs daily (rough — actual delays inside main())
0 7  * * *  cd /path/to/bot && /usr/bin/python -m src.x_bot.main >> logs/x_bot.log 2>&1
```

Or use APScheduler in-process for finer control.

## Files Cross-Reference

| Step | Doc |
|------|-----|
| Install + project layout | [02-installation-setup.md](./02-installation-setup.md) |
| Multi-account login | [03-authentication.md](./03-authentication.md) |
| Trending + search | [04-trending-search.md](./04-trending-search.md) |
| Reply creation | [05-reply-tweet.md](./05-reply-tweet.md) |
| Hygiene + backoff | [06-rate-limits-bans.md](./06-rate-limits-bans.md) |

## Pre-Build Checklist

- [ ] 6 X accounts (verified email + phone, >3 months old preferred)
- [ ] 6 residential proxy endpoints (one per account)
- [ ] 2FA enabled on each, TOTP secrets stored
- [ ] First-time browser login on each (build session)
- [ ] AI provider chosen (Claude / GPT / Gemini)
- [ ] Decision: fully-auto vs semi-auto (recommended: semi-auto for first month)
- [ ] Hosting (local cron / VPS / Docker)
- [ ] Burner accounts ready (2 extras)
- [ ] Monitoring (alert on >2 consecutive failures per account)
