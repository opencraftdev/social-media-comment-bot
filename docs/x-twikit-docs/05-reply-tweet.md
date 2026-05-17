# 05 — Reply to Tweets (Auto-Comment)

> **The core feature for our bot.** Single API call — no two-step like Threads.

## `create_tweet()` — Full Signature

```python
async client.create_tweet(
    text: str = '',
    media_ids: list[str] | None = None,
    poll_uri: str | None = None,
    reply_to: str | None = None,                  # ← TWEET ID TO REPLY TO
    conversation_control: Literal['followers', 'verified', 'mentioned'] | None = None,
    attachment_url: str | None = None,            # for quote tweets
    community_id: str | None = None,
    share_with_followers: bool = False,
    is_note_tweet: bool = False,                  # Premium: longer tweets
    richtext_options: list[dict] | None = None,   # Premium
    edit_tweet_id: str | None = None              # Premium
) -> Tweet
```

## Reply to Any Tweet — Basic

```python
await client.create_tweet(
    text='Great point! Have you considered X?',
    reply_to='1789012345678901234'   # ← target tweet's ID
)
```

That's it. One call. The reply appears under the target tweet.

## Reply with Media

```python
media_id = await client.upload_media('chart.png')
await client.create_tweet(
    text='Adding some data to this:',
    media_ids=[media_id],
    reply_to='1789012345678901234'
)
```

## Quote Tweet (Different from Reply)

```python
target_url = 'https://x.com/user/status/1789012345678901234'
await client.create_tweet(
    text='Sharing this with my thoughts',
    attachment_url=target_url
)
```

## Restrict Who Can Reply to Your Reply

```python
await client.create_tweet(
    text='...',
    reply_to='...',
    conversation_control='followers'   # only your followers can reply
)
```

## Reply Pipeline for Our Bot

```python
async def post_reply(client, account, target_tweet, ai_text, db):
    # 1) Safety checks
    if len(ai_text) > 280:
        ai_text = ai_text[:277] + '...'

    # 2) Dedup — never reply twice from same account to same tweet
    if await db.has_replied(account.username, target_tweet.id):
        return None

    # 3) Post
    try:
        reply = await client.create_tweet(
            text=ai_text,
            reply_to=target_tweet.id
        )
    except Exception as e:
        await db.log_failure(account.username, target_tweet.id, str(e))
        raise

    # 4) Record
    await db.record_reply(
        account=account.username,
        parent_tweet_id=target_tweet.id,
        parent_tweet_text=target_tweet.text,
        parent_author=target_tweet.user.screen_name,
        reply_id=reply.id,
        reply_text=ai_text,
    )

    return reply
```

## Other Engagement Actions (Use Sparingly)

```python
await client.favorite_tweet(tweet.id)            # like
await client.retweet(tweet.id)                   # retweet
await client.unfavorite_tweet(tweet.id)
await client.delete_retweet(tweet.id)
await client.delete_tweet(my_reply.id)           # in case of mistake
```

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `TooManyRequests` | Replied too fast | Back off 15-30 min |
| `Forbidden` | Account locked or target restricts replies | Skip target, alert ops |
| `BadRequest` | Empty text + no media, or text > 280 | Validate before sending |
| `NotFound` | Target tweet deleted | Skip + remove from queue |
| `LoginFlowException` mid-run | Session invalidated | Re-login |

## Character Limit Reminder

- Free account: **280 chars**
- X Premium: **25,000 chars** (set `is_note_tweet=True`)
- Emojis count as multiple chars (UTF-16 code units)

## What NOT to Do (Ban Triggers)

| Anti-Pattern | Why It's Risky |
|--------------|---------------|
| Same `text` across multiple targets | X detects template spam → instant flag |
| Reply within seconds of fetching | Looks like a bot — add 60-300s delay |
| Reply to >20 tweets in an hour | Triggers velocity flag |
| All 6 accounts active at same time | Coordinated cluster detection |
| Reply mostly to high-follower accounts | "Engagement bait" classifier |
| Reply with only links | Spam classifier |

See [06-rate-limits-bans.md](./06-rate-limits-bans.md) for full hygiene rules.
