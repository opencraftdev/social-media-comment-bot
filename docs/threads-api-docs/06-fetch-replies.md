# 06 — Fetch Replies on a Post

> Source: https://developers.facebook.com/docs/threads/retrieve-and-manage-replies/replies-and-conversations
> **Use case: avoid posting duplicate replies; show context to AI.**

## Two Endpoints

### `/replies` — Top-Level Only

```
GET https://graph.threads.net/v1.0/{media-id}/replies
```

Returns **only direct replies** to the post.

### `/conversation` — Full Tree

```
GET https://graph.threads.net/v1.0/{media-id}/conversation
```

Returns **all replies at all depths** (entire conversation tree).

## Required Permissions

- `threads_basic`
- `threads_read_replies` (app review required)

## Parameters

| Param | Type | Description |
|-------|------|-------------|
| `reverse` | bool | `true` (default) = newest first, `false` = oldest first |
| `fields` | csv | Fields to return |
| `access_token` | string | OAuth token |

## Returned Fields

```
id, text, username, timestamp, media_type,
has_replies, root_post, replied_to, is_reply, hide_status
```

- `root_post` — the original top post ID
- `replied_to` — the immediate parent reply ID
- `hide_status` — `NOT_HUSHED`, `UNHUSHED`, `HIDDEN`, `COVERED`, `BLOCKED`, `RESTRICTED`

## Example — Get Top-Level Replies

```bash
curl -X GET \
  -F "fields=id,text,username,timestamp" \
  -F "access_token=$THREADS_TOKEN" \
  "https://graph.threads.net/v1.0/17841400000000001/replies"
```

Response:

```json
{
  "data": [
    {
      "id": "17999999999999999",
      "text": "Totally agree with this",
      "username": "alice",
      "timestamp": "2026-05-17T09:00:00+0000"
    }
  ],
  "paging": { "cursors": { "before": "...", "after": "..." } }
}
```

## For Our Bot — Duplicate Prevention

Before posting a reply, check if any of our 5-6 accounts already replied:

```
function alreadyReplied(parentPostId, ourUsernames):
    replies = GET /{parentPostId}/replies?fields=username
    for r in replies.data:
        if r.username in ourUsernames:
            return true
    return false
```

Cheaper alternative: **track in local DB** (avoids API call) — see [05-create-reply.md](./05-create-reply.md) reply pipeline.

## ⚠️ Caveat

Reading replies on **third-party** posts isn't guaranteed for all posts — some authors restrict visibility. Use local DB as the primary dedup mechanism.
