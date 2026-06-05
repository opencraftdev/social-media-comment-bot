# OpenCraft Social Bot

Semi-automated social media reply bot for [@opencraft.dev](https://threads.net/@opencraft.dev) (Threads) and [@opencraftdev](https://x.com/opencraftdev) (X).

Discovers viral posts → drafts brand-aware replies via Claude → human approves → posts via official APIs.

## Quick Start

```bash
# 1. Activate venv
source .venv/bin/activate

# 2. Copy and fill in your keys
cp .env.example .env
# Required: ANTHROPIC_API_KEY, STEEL_API_KEY, SUPABASE_URL, SUPABASE_KEY,
#           THREADS_ACCESS_TOKEN, X_USERNAME, X_PASSWORD, X_EMAIL

# 3. Verify everything is wired up
python -m src.cli status
```

## Running the Daemon

The daemon polls Supabase for commands from the web UI and executes scrape → draft → post automatically.

```bash
python -m src.cli daemon --interval 15
```

`--interval` is the polling interval in seconds (default: 60). With `--interval 15` it checks for new commands every 15 seconds.

The daemon handles:
- Scraping viral posts on Threads and X
- Drafting brand-aware replies via Claude
- Posting approved replies on command from the web UI

## Manual Commands

In Claude Code: just say it. The brain ([CLAUDE.md](CLAUDE.md)) maps phrases to commands.

| Say | Runs |
|-----|------|
| "please scrape" | `python -m src.cli scrape --platform all` |
| "draft" | invokes `reply-drafter` subagent |
| "queue" | `python -m src.cli queue --status ready_for_review` |
| "status" | `python -m src.cli status` |
| "approve 42" | `python -m src.cli approve --id 42` |
| "post 42" | `python -m src.cli post --id 42` |
| "full run today" | invokes `social-bot` skill |

Or run directly:

```bash
python -m src.cli scrape --platform all     # scrape both platforms
python -m src.cli scrape --platform threads # threads only
python -m src.cli scrape --platform x       # x only
python -m src.cli queue --status ready_for_review
python -m src.cli approve --id <id>
python -m src.cli post --id <id>
python -m src.cli post --all-approved
python -m src.cli status
```

## Project Layout

```
brand/                  ← OpenCraft brand profile (drives AI voice)
src/
  ├── cli.py            ← unified entrypoint
  ├── brand/loader.py   ← brand profile loader
  ├── queue/db.py       ← Supabase-backed queue
  ├── scraper/
  │   ├── threads_spider.py  ← Steel + Playwright scraper
  │   └── x_spider.py        ← Steel + Playwright scraper (twikit auth)
  ├── ai/draft.py       ← Claude API drafting
  ├── poster/
  │   ├── threads_poster.py  ← official Threads API
  │   └── x_poster.py        ← twikit
  └── command_poller.py ← Supabase bot_commands polling (daemon)
docs/
  ├── threads-api-docs/ ← Official Threads API reference
  └── x-twikit-docs/    ← twikit reference
.claude/skills/social-bot/SKILL.md  ← end-to-end workflow skill
CLAUDE.md               ← project brain (auto-loads in sessions)
```

## Setup

```bash
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
cp .env.example .env
```

## Hard Rules

- Never post without explicit per-item approval
- Respect `operational_caps` in `brand/brand-profile.json` (5 replies/day per platform)
- AI draft voice must come from `brand/brand-profile.json` only
- Never commit `.env`, `accounts/`, `data/*.db`
