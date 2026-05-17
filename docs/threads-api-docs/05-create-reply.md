# 05 — Create Reply (Comment on Others' Posts)

> Source: https://developers.facebook.com/docs/threads/posts
> **This is the core "auto-comment" feature for our bot.**

## Two-Step Flow (Same as Regular Posts)

```
Step 1: Create reply container  → POST /{user-id}/threads
        body includes: reply_to_id, text, media_type
        → returns { id: <creation_id> }

Step 2: Publish container       → POST /{user-id}/threads_publish
        body: { creation_id }
        → returns { id: <media_id> }
```

## Required Permissions

- `threads_basic`
- `threads_content_publish`

> ℹ️ Replying to a **public** third-party post only requires `threads_content_publish`. You found the post ID via keyword search ([04-keyword-search.md](./04-keyword-search.md)).

## Step 1 — Create Reply Container

```
POST https://graph.threads.net/v1.0/{user-id}/threads
```

### Parameters

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `media_type` | string | ✅ | `TEXT`, `IMAGE`, `VIDEO`, `CAROUSEL` |
| `text` | string | ⚠️ | Reply content, **max 500 chars** (UTF-8 byte counted) |
| `reply_to_id` | string | ✅ for reply | **The target post ID** (from keyword search) |
| `image_url` | string | conditional | For `IMAGE` type — public URL |
| `video_url` | string | conditional | For `VIDEO` type — public URL |
| `reply_control` | string | | Who can reply to YOUR reply (see below) |
| `topic_tag` | string | | 1-50 chars, no `.` or `&` |
| `link_attachment` | string | | URL (text-only posts, max 5) |
| `gif_attachment` | string | | GIPHY URL (text-only posts) |
| `allowlisted_country_codes` | csv | | ISO codes (geo-restrict reply) |
| `access_token` | string | ✅ | OAuth token |

### `reply_control` Values

- `everyone` (default)
- `accounts_you_follow`
- `mentioned_only`
- `parent_post_author_only`
- `followers_only`

### Example — Reply to a Post

```bash
curl -X POST \
  -F "media_type=TEXT" \
  -F "text=Great take! AI agents will reshape SaaS by 2027." \
  -F "reply_to_id=17841400000000001" \
  -F "access_token=$THREADS_TOKEN" \
  "https://graph.threads.net/v1.0/$USER_ID/threads"
```

Response:

```json
{ "id": "17999999999999999" }
```

Save this as `creation_id` for Step 2.

## Step 2 — Publish the Reply

```
POST https://graph.threads.net/v1.0/{user-id}/threads_publish
```

### Parameters

| Param | Type | Required |
|-------|------|----------|
| `creation_id` | string | ✅ |
| `access_token` | string | ✅ |

### Example

```bash
curl -X POST \
  -F "creation_id=17999999999999999" \
  -F "access_token=$THREADS_TOKEN" \
  "https://graph.threads.net/v1.0/$USER_ID/threads_publish"
```

Response:

```json
{ "id": "17888888888888888" }   // ← the published reply's media ID
```

## Best Practices

- Container processing takes a few seconds. Meta recommends polling container status **once per minute, max 5 minutes** before publishing.
- For text-only replies, you can usually skip status polling (instant).
- For media replies (image/video), check status:

```bash
curl -X GET \
  "https://graph.threads.net/v1.0/{creation_id}?fields=status,error_message&access_token=$THREADS_TOKEN"
```

Status values: `IN_PROGRESS`, `FINISHED`, `ERROR`, `EXPIRED`.

## Constraints

- **Text:** 500 chars (emojis = multiple bytes)
- **Reply rate limit:** 1,000 replies / 24h / account (see [07-rate-limits.md](./07-rate-limits.md))
- **Container expiry:** unpublished containers expire after 24h
- **No editing** after publish — only delete

## For Our Bot — Reply Pipeline

```
function postReply(account, parentPostId, aiCommentText):
    // 1. Create container
    creation = POST /{account.user_id}/threads
        body: {
            media_type: "TEXT",
            text: aiCommentText,
            reply_to_id: parentPostId,
            access_token: account.token
        }

    // 2. (Optional) poll status — usually instant for text
    sleep(2s)

    // 3. Publish
    media = POST /{account.user_id}/threads_publish
        body: {
            creation_id: creation.id,
            access_token: account.token
        }

    // 4. Record in local DB to prevent duplicate replies
    db.save({
        account: account.username,
        parent_post: parentPostId,
        reply_media_id: media.id,
        timestamp: now()
    })

    return media.id
```

## Reply Cap Math for Our Bot

```
1,000 replies / 24h / account (API limit)
× 6 accounts = 6,000 replies/day max
```

We'll cap at **5-10 replies / account / day** = 30-60/day total — well under limits and looks human.
