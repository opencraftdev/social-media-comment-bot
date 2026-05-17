# 07 — Rate Limits & Quotas

> Source: https://developers.facebook.com/docs/threads/troubleshooting

## Per-Account Quotas (24-hour rolling)

| Operation | Limit / 24h | Endpoint | Our Bot Uses? |
|-----------|-------------|----------|----------------|
| **Publishing posts** | 250 | `POST /{user-id}/threads_publish` | Indirect (via replies) |
| **Publishing replies** | **1,000** | `POST /{user-id}/threads_publish` (with `reply_to_id`) | ✅ **Core** |
| Deleting content | 100 | `DELETE /{media-id}` | Rarely |
| ~~Location search~~ | 500 | location search endpoint | ❌ Skipped |
| ~~Keyword search~~ | ~~2,200~~ | ~~`GET /keyword_search`~~ | ❌ **Skipped** (no app review) |

All quotas use a rolling 24-hour window (`quota_duration: 86400 seconds`).

## Check Quota Usage

```
GET https://graph.threads.net/v1.0/{user-id}/threads_publishing_limit
```

### Fields

```
quota_usage, config,
reply_quota_usage, reply_config,
delete_quota_usage, delete_config,
location_search_quota_usage, location_search_config
```

### Example

```bash
curl -X GET \
  -F "fields=quota_usage,config,reply_quota_usage,reply_config" \
  -F "access_token=$THREADS_TOKEN" \
  "https://graph.threads.net/v1.0/$USER_ID/threads_publishing_limit"
```

Response:

```json
{
  "data": [{
    "quota_usage": 3,
    "config": { "quota_total": 250, "quota_duration": 86400 },
    "reply_quota_usage": 47,
    "reply_config": { "quota_total": 1000, "quota_duration": 86400 }
  }]
}
```

For our bot, focus on `reply_quota_usage` — that's the metric that matters.

## Best Practices (per Meta)

- Poll container status **once per minute, NOT more than 5 minutes** total
- Check quota before bulk operations

## For Our Bot — Math

With 6 accounts × 5-10 replies/day:

| Resource | Used | Limit | Headroom |
|----------|------|-------|----------|
| Replies / account / day | 5-10 | 1,000 | 99% |

We're operating at **<1% of API limits** — bottleneck is platform anti-spam detection (human-like behavior), not quotas.

## Anti-Ban Hygiene (NOT in docs — operational wisdom)

| Pattern | Risk | Mitigation |
|---------|------|------------|
| Replies within seconds of each other | 🔴 High | Random delay 60-300s between actions |
| Same/template comments | 🔴 High | AI variation per post |
| All accounts active simultaneously | 🟡 Med | Stagger schedules across the day |
| New accounts hitting full quota | 🔴 High | Warm up — 1-2 replies/day for first 2 weeks |
| Same IP for all accounts | 🟡 Med | Residential proxies, one per account |
| Posting 24/7 | 🟡 Med | Respect each account's "timezone" (8h on, 16h off) |

## Error Codes (Inferred — Not Fully Documented)

| HTTP | Meaning | Action |
|------|---------|--------|
| `4` / `17` / `32` | App-level rate limit | Back off 1 hour |
| `4` (subcode `2207051`) | User rate limit | Pause that account 24h |
| `190` | Token expired/invalid | Refresh / re-auth |
| `200` (subcode `2207026`) | Permission missing | Check scopes |
| `100` (subcode `2207042`) | Container expired (>24h) | Recreate |
