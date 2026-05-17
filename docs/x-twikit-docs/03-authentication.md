# 03 — Authentication

## Method 1: Username/Password (First Login)

```python
import asyncio
from twikit import Client

async def main():
    client = Client('en-US')
    await client.login(
        auth_info_1='username_or_screen_name',
        auth_info_2='email@example.com',     # optional but recommended
        password='your_password',
        cookies_file='accounts/acc1.cookies.json'   # auto-saves
    )

asyncio.run(main())
```

### `login()` Parameters

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `auth_info_1` | str | ✅ | Username or screen name |
| `auth_info_2` | str | recommended | Email (helps avoid challenges) |
| `password` | str | ✅ | Account password |
| `totp_secret` | str | for 2FA | Base32 TOTP secret (see below) |
| `cookies_file` | str | recommended | Path to save session cookies |
| `enable_ui_metrics` | bool | | UI metrics simulation (anti-bot) |

Returns: `dict` with login response.

## Method 2: Load Existing Cookies (Subsequent Runs)

```python
client = Client('en-US')
client.load_cookies('accounts/acc1.cookies.json')
# No login needed — session restored
```

**Always prefer this for repeated runs.** Logging in too often triggers X's anti-bot.

## Method 3: Smart Fallback (Recommended)

```python
import os
from twikit import Client

async def get_client(account):
    client = Client('en-US')
    cookies_path = f'accounts/{account.username}.cookies.json'

    if os.path.exists(cookies_path):
        client.load_cookies(cookies_path)
        # Optional: verify by making a cheap call
        try:
            await client.user()
            return client
        except Exception:
            pass  # cookies expired, fall through to login

    await client.login(
        auth_info_1=account.username,
        auth_info_2=account.email,
        password=account.password,
        totp_secret=account.totp_secret,
        cookies_file=cookies_path
    )
    return client
```

## 2FA / TOTP Setup

If accounts have 2FA enabled (recommended for security):

1. In X settings → enable 2FA → **Authentication app**
2. X shows a QR code AND a base32 secret string (e.g., `JBSWY3DPEHPK3PXP`)
3. Save that string as `TOTP_SECRET` in `.env`
4. Pass to `login()`:

```python
await client.login(
    auth_info_1='username',
    auth_info_2='email',
    password='password',
    totp_secret='JBSWY3DPEHPK3PXP',
    cookies_file='...'
)
```

twikit generates the 6-digit code on the fly.

## Proxy Support (Anti-Ban)

```python
client = Client(
    'en-US',
    proxy='socks5://user:pass@proxy.example.com:1080'
    # or http://user:pass@proxy:port
)
```

**One proxy per account.** Residential proxies > datacenter proxies.

## Multi-Account Manager Pattern

```python
# src/x_bot/account_manager.py
from dataclasses import dataclass
from twikit import Client

@dataclass
class Account:
    username: str
    email: str
    password: str
    totp_secret: str | None
    proxy: str | None
    cookies_path: str
    daily_reply_cap: int = 8

class AccountManager:
    def __init__(self, accounts: list[Account]):
        self.accounts = accounts
        self.clients: dict[str, Client] = {}

    async def get_client(self, username: str) -> Client:
        if username in self.clients:
            return self.clients[username]

        acc = next(a for a in self.accounts if a.username == username)
        client = Client('en-US', proxy=acc.proxy)

        if os.path.exists(acc.cookies_path):
            client.load_cookies(acc.cookies_path)
        else:
            await client.login(
                auth_info_1=acc.username,
                auth_info_2=acc.email,
                password=acc.password,
                totp_secret=acc.totp_secret,
                cookies_file=acc.cookies_path,
            )

        self.clients[username] = client
        return client
```

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `LoginFlowException` | Captcha / suspicious login | Login manually in browser first, copy cookies → use `load_cookies()` |
| `Forbidden 399` | Account locked | Check email — X may require phone verification |
| `Unauthorized 401` | Cookies expired | Delete cookies file, re-login |
| `BadRequest 400 acid_challenge` | Login challenge | Add `auth_info_2` (email), use TOTP, try residential proxy |
| Login hangs | IP flagged | Try different proxy, or login from accountʼs usual location |

## Manual Cookie Extraction (If Auto-Login Keeps Failing)

1. Login to x.com in Chrome
2. DevTools → Application → Cookies → x.com
3. Find these cookies:
   - `auth_token`
   - `ct0`
   - `guest_id`
   - `personalization_id`
   - `twid`
4. Save as JSON:

```json
{
  "auth_token": "abc123...",
  "ct0": "def456...",
  "guest_id": "v1%3A...",
  "personalization_id": "v1_...",
  "twid": "u%3D1234567890"
}
```

5. Load: `client.load_cookies('manual_cookies.json')`

## Security

- **Never commit cookies.json** — they're session tokens, anyone with them can hijack the account
- Encrypt at rest in production (e.g., `cryptography.fernet`)
- Rotate cookies if leaked (logout in browser → invalidates token)
