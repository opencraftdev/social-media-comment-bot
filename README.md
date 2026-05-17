# OpenCraft Social Bot

Semi-automated social media reply bot for [@opencraft.dev](https://threads.net/@opencraft.dev) (Threads) and [@opencraftdev](https://x.com/opencraftdev) (X).

Discovers viral posts → drafts brand-aware replies via Claude → human approves → posts via official APIs.

## Quick Start

```bash
# 1. Activate venv (already set up)
source .venv/bin/activate

# 2. Edit .env with your keys
# Required: ANTHROPIC_API_KEY, ZERNIO_API_KEY, THREADS_*, X_*

# 3. Verify
python -m src.cli status
python -m src.cli brand-show
```

## How to Use

In Claude Code: just say it. The brain ([CLAUDE.md](CLAUDE.md)) maps phrases to commands.

| Say | Runs |
|-----|------|
| "please scrape" | `python -m src.cli scrape --platform all` |
| "draft" | `python -m src.cli draft --limit 5` |
| "queue" | `python -m src.cli queue` |
| "status" | `python -m src.cli status` |
| "approve 42" | `python -m src.cli approve --id 42` |
| "post 42" | `python -m src.cli post --id 42` |
| "full run today" | invokes `social-bot` skill |

## Project Layout

```
brand/                  ← OpenCraft brand profile (drives AI voice)
docs/
  ├── threads-api-docs/ ← Official Threads API reference
  └── x-twikit-docs/    ← twikit (unofficial X) reference
src/
  ├── cli.py            ← unified entrypoint
  ├── brand/loader.py   ← ✅ implemented
  ├── queue/db.py       ← ✅ implemented (SQLite)
  ├── scraper/          ← 🚧 stubbed (Playwright + twikit)
  ├── ai/draft.py       ← 🚧 stubbed (Claude API)
  └── poster/           ← 🚧 stubbed (Threads + X posters)
.claude/skills/social-bot/SKILL.md  ← end-to-end workflow
CLAUDE.md               ← project brain (auto-loads in sessions)
```

## Setup (Already Done)

```bash
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
cp .env.example .env
.venv/bin/python -m src.cli status  # creates data/bot.db
```

## What Works Today

- ✅ `status`, `brand-show`, `queue`, `approve`, `skip` (full CRUD)
- 🚧 `scrape`, `draft`, `post`, `brand-refresh` (stubbed with clear TODOs)

## Next Build

See implementation order in [CLAUDE.md](CLAUDE.md). Recommended:
1. `src/ai/draft.py` (Claude API + brand-conditioned prompt)
2. `src/scraper/x_spider.py` (twikit)
3. `src/poster/x_poster.py` (twikit reply)
4. `src/scraper/threads_spider.py` (Playwright)
5. `src/poster/threads_poster.py` (httpx → official Threads API)

## Hard Rules

- Never post without explicit per-item approval
- Respect `operational_caps` in `brand/brand-profile.json` (5 replies/day per platform)
- AI draft voice must come from `brand/brand-profile.json` only
- Never commit `.env`, `accounts/`, `data/*.db`

## Risk Reminder

The Zernio API key was shared in chat history during setup — **rotate it** at zernio.com → API settings.
