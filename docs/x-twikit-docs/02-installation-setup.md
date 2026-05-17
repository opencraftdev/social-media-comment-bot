# 02 — Installation & Setup

## Requirements

- Python **3.10+** (uses modern async features)
- pip / poetry / uv (any package manager)

## Install

```bash
pip install twikit
```

Or pin the version (recommended for production):

```bash
pip install twikit==2.3.3
```

## Project Structure (Suggested)

```
social-media-comment-bot/
├── docs/
│   ├── threads-api-docs/
│   └── x-twikit-docs/
├── src/
│   ├── x_bot/
│   │   ├── __init__.py
│   │   ├── client_factory.py     # twikit client per account
│   │   ├── trending.py           # get_trends + search_tweet
│   │   ├── replier.py            # create_tweet with reply_to
│   │   └── account_manager.py    # rotation, quotas
│   ├── ai/
│   │   └── comment_generator.py  # Claude/OpenAI wrapper
│   └── main.py
├── accounts/
│   ├── account_1.cookies.json
│   ├── account_2.cookies.json
│   └── ...
├── data/
│   └── replies.db                # SQLite for dedup + audit
├── requirements.txt
└── .env                          # account creds (gitignored)
```

## requirements.txt (Starter)

```
twikit==2.3.3
anthropic            # for Claude-based comment generation
python-dotenv        # env config
aiosqlite            # async SQLite for dedup
httpx[socks]         # for SOCKS proxy support (anti-ban)
```

## .env Template

```bash
# Account 1
ACC1_USERNAME=user1
ACC1_EMAIL=user1@example.com
ACC1_PASSWORD=supersecret
ACC1_TOTP_SECRET=ABCDEFGHIJK    # optional, for 2FA
ACC1_PROXY=socks5://user:pass@proxy1.example.com:1080

# Account 2
ACC2_USERNAME=user2
# ...

# AI
ANTHROPIC_API_KEY=sk-ant-...
```

**Never commit `.env` or `cookies.json` files.** Add to `.gitignore`:

```
.env
accounts/*.cookies.json
data/*.db
__pycache__/
```

## Smoke Test

```python
# tests/smoke.py
import asyncio
from twikit import Client

async def main():
    client = Client('en-US')
    await client.login(
        auth_info_1='your_username',
        auth_info_2='your_email',
        password='your_password',
        cookies_file='accounts/test.cookies.json'
    )

    trends = await client.get_trends('trending')
    print(f"✓ Logged in, got {len(trends)} trends")
    for t in trends[:3]:
        print(f"  - {t.name}")

asyncio.run(main())
```

Expected output:

```
✓ Logged in, got 20 trends
  - #SomeTrend
  - SomeTopic
  - AnotherThing
```

If you see captcha errors or `LoginFlowException`, see [03-authentication.md](./03-authentication.md) → Troubleshooting.
