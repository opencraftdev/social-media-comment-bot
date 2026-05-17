# OpenCraft Social Bot — Project Brain

> This file auto-loads in every Claude Code session in this repo. It is the brain that maps natural-language phrases to bot commands. Read it first.

## What This Project Is

A semi-automated social media reply bot for the **OpenCraft** brand. It:

1. **Scrapes** viral posts on Threads (Playwright) and X (twikit) matching brand keywords
2. **Drafts** brand-aware replies via Claude API using `brand/brand-profile.json`
3. **Queues** drafts for human approval (semi-auto by default)
4. **Posts** approved replies via official Threads API + twikit
5. **Logs** everything to local SQLite for dedup + audit

Single account per platform: `@opencraft.dev` (Threads) and `@opencraftdev` (X).

## Brand Identity — Reference Before Any AI Drafting

Full machine-readable profile: [brand/brand-profile.json](brand/brand-profile.json)

**Always preload before drafting:**

- **Voice:** operator-grade, calm, anti-hype, slightly contrarian
- **Niche:** Claude Code, MCP, agentic dev tools, AI rollout in teams
- **Anti-niche:** generic hype, AGI debate, crypto, politics, sports
- **Language:** Bahasa Indonesia primary + English tech terms (workflow, ship, MCP, diff, patch)
- **Promotion:** value-first, NEVER "check my profile", soft brand signal ~1 in 10 replies
- **Reply modes:** rotate `agree_and_extend` / `polite_contrarian` / `concrete_example` / `ask_sharpening_question`
- **Caps:** 5 replies/day per platform, 90-300s delay between actions, 8h active window

## Natural Language → Command Map

When the user types any of these phrases, **run the matched command immediately** via Bash. Do not ask for clarification on common phrasings.

| User phrase (any of) | Run |
|----------------------|------|
| "please scrape", "scrape now", "find viral", "discover", "pull trending" | `python -m src.cli scrape --platform all` |
| "scrape threads", "find threads posts", "viral on threads" | `python -m src.cli scrape --platform threads` |
| "scrape x", "scrape twitter", "find tweets", "viral on x" | `python -m src.cli scrape --platform x` |
| "scrape lax", "test scrape" (relaxed engagement+age filters) | append `--lax` to the scrape command |
| **"check scrapers"**, "scraper status", "scraper health", "are scrapers working", "scraper diagnostics" | `python -m src.cli scrapers` |
| **"probe scrapers"**, "test x session", "verify cookies" | `python -m src.cli scrapers --probe` |
| "x login", "login x", "re-login x", "x cookies expired" | `python -m src.cli x-login` (opens visible browser) |
| "test x", "verify x" | `python -m src.cli x-test` |
| "threads login", "login threads", "threads cookies", "threads cookies expired", "re-login threads" | `python -m src.cli threads-login` (opens visible browser) |
| "test threads", "verify threads", "check threads session" | `python -m src.cli threads-test` |
| "draft", "draft replies", "generate replies", "write drafts" | **Invoke the `reply-drafter` subagent via Task tool** (subagent_type=`reply-drafter`). Do NOT run `python -m src.cli draft` for drafting — that command only reports pending items. The subagent reads the queue, generates Bahasa replies per-item using brand voice, and saves to DB. |
| "draft #<id>", "draft item <id>", "redraft <id>" | Invoke `reply-drafter` subagent with prompt: "draft item #<id>" |
| "queue", "show queue", "pending", "what's queued", "review queue" | `python -m src.cli queue --status ready_for_review` |
| "approve <id>" | `python -m src.cli approve --id <id>` |
| "post <id>", "publish <id>", "send <id>" | `python -m src.cli post --id <id>` |
| "post all approved", "publish approved" | `python -m src.cli post --all-approved` |
| "status", "stats", "how's the bot", "daily count" | `python -m src.cli status` |
| "report", "show report", "reply table", "what got replied", "who did we reply to" | `python -m src.cli report` |
| "reload brand", "refresh brand profile" | re-read [brand/brand-profile.json](brand/brand-profile.json) and confirm key fields |
| "rebuild brand from zernio" | `python -m src.cli brand-refresh` |
| "skip <id>", "reject <id>" | `python -m src.cli skip --id <id>` |
| "full run today", "daily cycle", "do today's run" | invoke the `social-bot` skill |

For anything outside this map, invoke the **`social-bot` skill** at [.claude/skills/social-bot/SKILL.md](.claude/skills/social-bot/SKILL.md) for the full reference.

## Custom Subagents

| Subagent | When to invoke | Where |
|----------|---------------|-------|
| **`reply-drafter`** | Any draft-related request. The brain MUST use the Task tool with `subagent_type="reply-drafter"`. Pass the user's intent as the prompt (e.g. "draft 5 replies", "draft #42", "redraft #91"). | [.claude/agents/reply-drafter.md](.claude/agents/reply-drafter.md) |

**Rule:** Drafting reply text is the subagent's job — never call `claude -p` subprocess, never use anthropic SDK from inside Python. The subagent reads/writes the DB via the CLI helpers `list-scraped` and `save-draft`.

## Hard Behavioral Rules

1. **NEVER post without explicit user approval** of that specific queue item. Even in "fully auto" mode, default to semi-auto for now.
2. **ALWAYS load `brand/brand-profile.json`** before any AI drafting. Never improvise the brand voice.
3. **Respect `operational_caps`** in the brand profile. If `replies_per_day` for a platform is hit, refuse to post and tell the user.
4. **Use random delays** 90-300s between posts. Never burst.
5. **NEVER paste OpenCraft URLs** in replies. Soft brand signals only (see `promotion.soft_cta_examples`).
6. **Anti-topics filter:** if a viral post matches `niche.anti_topics`, skip and log — don't ask the user.
7. **Dedup is local-first:** check `data/bot.db` `replies` table before queuing or posting.
8. **Token health:** before posting, verify the platform's access token has >7 days until expiry.
9. **Secrets:** API keys live in `.env` (gitignored). NEVER commit `.env`, `cookies.json`, or `data/*.db`.
10. **Risk mode:** if a scraper or poster returns an auth error or 429, **pause that platform for 1 hour** and notify the user. Do not retry in a loop.

## Project Layout

```
brand/                                # already done — brand profile
  ├── brand-profile.json
  └── README.md

src/
  ├── cli.py                          # unified entrypoint
  ├── brand/loader.py                 # loads brand-profile.json
  ├── scraper/
  │   ├── threads_spider.py           # Playwright
  │   └── x_spider.py                 # twikit
  ├── ai/draft.py                     # Claude API + brand context
  ├── poster/
  │   ├── threads_poster.py           # httpx → official Threads API
  │   └── x_poster.py                 # twikit create_tweet
  └── queue/db.py                     # SQLite schema + helpers

data/
  └── bot.db                          # SQLite, gitignored

docs/
  ├── threads-api-docs/               # already done
  └── x-twikit-docs/                  # already done

.claude/
  └── skills/social-bot/SKILL.md      # full end-to-end workflow skill
```

## Tooling

- Python 3.10+
- Playwright (`playwright install chromium`)
- twikit, anthropic, httpx, aiosqlite
- Cookies and access tokens persisted in `accounts/` (gitignored)

## Status Convention (Queue Table)

| Status | Meaning |
|--------|---------|
| `scraped` | Discovered by scraper, not yet drafted |
| `draft_pending` | Awaiting AI draft |
| `ready_for_review` | AI drafted, awaiting human approval |
| `approved` | User said yes, ready to post |
| `posted` | Successfully published |
| `failed` | Post attempt failed (see `error` field) |
| `skipped` | User rejected OR auto-filtered |

## What NOT to Do

- ❌ Run the bot in fully-auto mode in your first 2 weeks
- ❌ Build any feature not mapped to a real brand goal — check brand-profile.json
- ❌ Add Instagram automation (Meta bans aggressively; we only POST on IG via Zernio manually)
- ❌ Add LinkedIn / TikTok / Facebook without discussion
- ❌ Inline brand logic in code — always read from `brand/brand-profile.json`

## Quick Health Check Any Session

If user is unsure where things are, run:

```bash
python -m src.cli status
```

It reports: daily reply count vs cap, token expiry days, last scrape time, queue depth by status.
