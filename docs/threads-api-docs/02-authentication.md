# 02 — Authentication & Token Lifecycle

> Source: https://developers.facebook.com/docs/threads/get-started

## App Setup (One-Time)

1. Go to [developers.facebook.com](https://developers.facebook.com/) → My Apps → Create App
2. Select **"Threads use case"**
3. You'll receive **2 sets** of credentials — use the **Threads-specific App ID & Secret**, not the Facebook ones
4. Configure OAuth redirect URI (must be HTTPS)
5. Add Threads testers under App Roles (for development)

## OAuth Flow — 3 Steps

### Step 1: Authorization URL (User Consent)

Direct each account to:

```
https://threads.net/oauth/authorize
  ?client_id={THREADS_APP_ID}
  &redirect_uri={REDIRECT_URI}
  &scope=threads_basic,threads_content_publish,threads_keyword_search,threads_manage_replies
  &response_type=code
```

User logs in → approves → redirected to:

```
{REDIRECT_URI}?code={AUTH_CODE}
```

### Step 2: Exchange Code → Short-Lived Token (1 hour)

```bash
curl -X POST https://graph.threads.net/oauth/access_token \
  -F client_id={THREADS_APP_ID} \
  -F client_secret={THREADS_APP_SECRET} \
  -F grant_type=authorization_code \
  -F redirect_uri={REDIRECT_URI} \
  -F code={AUTH_CODE}
```

Response:

```json
{
  "access_token": "THQVJ...",
  "user_id": 1234567890
}
```

### Step 3: Exchange → Long-Lived Token (60 days)

```bash
curl -X GET "https://graph.threads.net/access_token\
?grant_type=th_exchange_token\
&client_secret={THREADS_APP_SECRET}\
&access_token={SHORT_LIVED_TOKEN}"
```

Response:

```json
{
  "access_token": "THQVJ...",
  "token_type": "bearer",
  "expires_in": 5183944
}
```

## Refresh Long-Lived Token

Refresh **before** the 60-day expiry to keep account active without re-auth:

```bash
curl -X GET "https://graph.threads.net/refresh_access_token\
?grant_type=th_refresh_token\
&access_token={LONG_LIVED_TOKEN}"
```

Returns new 60-day token. Token must be **at least 24 hours old** to refresh.

## For Our Bot — 5-6 Accounts

Each account needs its own long-lived token. Store securely:

```
accounts/
  account_1.json   # { user_id, access_token, expires_at, username }
  account_2.json
  ...
```

Refresh logic (run daily):

```
for each account:
    if token expires in < 7 days:
        refresh
```

## Using the Token

Either method works:

```bash
# Header (preferred)
-H "Authorization: Bearer {TOKEN}"

# Query param
?access_token={TOKEN}
```
