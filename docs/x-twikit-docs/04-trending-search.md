# 04 — Trending Topics & Tweet Search

## `get_trends()` — Get Trending Topics

### Signature

```python
async client.get_trends(
    category: Literal['trending', 'for-you', 'news', 'sports', 'entertainment'],
    count: int = 20,
    retry: bool = True,
    additional_request_params: dict | None = None
) -> list[Trend]
```

### Categories

| Category | What |
|----------|------|
| `'trending'` | Global trending topics (region depends on account locale) |
| `'for-you'` | Personalized for the logged-in account |
| `'news'` | News-specific trends |
| `'sports'` | Sports trends |
| `'entertainment'` | Entertainment trends |

### Trend Object

```python
trend.name          # e.g., "#Election2026" or "ClimateChange"
# Additional fields exist; check object via dir(trend)
```

### Example

```python
trends = await client.get_trends('trending', count=30)
for t in trends:
    print(t.name)
```

### Picking the Right Category for Our Bot

| Account Niche | Recommended Category |
|---------------|----------------------|
| Tech / AI focus | `for-you` (after warming the account on tech topics) |
| News commentary | `news` |
| Sports analyst | `sports` |
| Generalist | `trending` |

## `search_tweet()` — Search for Tweets

### Signature

```python
async client.search_tweet(
    query: str,
    product: Literal['Top', 'Latest', 'Media'],
    count: int = 20,
    cursor: str | None = None
) -> Result[Tweet]
```

### Product Types

| Product | What |
|---------|------|
| `'Top'` | Highest-engagement tweets matching query (best for our bot) |
| `'Latest'` | Most recent tweets matching query |
| `'Media'` | Tweets with images/videos only |

### Query Syntax (X's standard operators work)

```
"ai agents"              # exact phrase
ai agents min_faves:100  # min likes
ai agents lang:en        # English only
ai agents -is:reply      # exclude replies
ai agents since:2026-05-15
from:elonmusk ai         # from a specific user
#AIagents OR #LLMs       # hashtags
```

### Tweet Object (Key Fields)

```python
tweet.id              # str, used as reply_to
tweet.text            # tweet content
tweet.created_at      # timestamp
tweet.lang            # language code
tweet.user            # User object
tweet.user.screen_name
tweet.user.followers_count
tweet.favorite_count  # likes
tweet.retweet_count
tweet.reply_count
tweet.view_count
tweet.is_quote_status
tweet.in_reply_to     # if it's a reply
tweet.urls
tweet.hashtags
tweet.media
```

### Pagination

```python
result = await client.search_tweet('ai agents', 'Top')
for tweet in result:
    print(tweet.text)

# Next page
more = await result.next()
```

## Combined: Trending → Search → Filter

```python
async def find_candidates(client, niche_keywords: list[str], hours: int = 6):
    candidates = []

    # 1) Pull trending
    trends = await client.get_trends('trending', count=30)
    trend_names = [t.name for t in trends]

    # 2) Build search queries (your niche keywords + relevant trends)
    queries = niche_keywords + [
        t for t in trend_names
        if any(kw.lower() in t.lower() for kw in niche_keywords)
    ]

    # 3) Search each query
    for q in queries[:5]:   # cap to 5 to save rate limit
        results = await client.search_tweet(
            f'{q} lang:en -is:reply min_faves:50',
            'Top',
            count=20
        )

        for tweet in results:
            # Filter
            if tweet.user.followers_count < 1000:
                continue
            if tweet.favorite_count < 50:
                continue
            if hours_since(tweet.created_at) > hours:
                continue
            candidates.append(tweet)

    # 4) Sort by engagement
    candidates.sort(
        key=lambda t: t.favorite_count + t.reply_count * 2,
        reverse=True
    )
    return candidates
```

## Rate Limits (Operational — Not Documented)

twikit hits X's internal API which has soft rate limits. Practical guidance:

| Action | Safe Rate per Account |
|--------|----------------------|
| `get_trends()` | 1 call every 10-30 min |
| `search_tweet()` | 1 call every 20-60s |
| Tweet fetches | 1 every 2-5s |

Sustained over ~15 min above this → `TooManyRequests`. Back off 15-30 min on hit.
