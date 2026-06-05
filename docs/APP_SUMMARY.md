# OpenCraft Social Bot — Integration Summary

Semi-automated social media reply bot for the **OpenCraft** brand on Threads (`@opencraft.dev`) and X (`@opencraftdev`).

## Flow

```
SCRAPE → DRAFT (Claude AI) → HUMAN REVIEW → APPROVE → POST → LOG
```

1. **Scrape** — Playwright searches Threads (public) and X (cookie-auth) for brand keywords. Filters: Indonesian language, min engagement, max 48h age, anti-topics (crypto/politics/sports), spam words. Saves to DB as `scraped`.
2. **Draft** — Claude AI reads each `scraped` item + brand profile JSON, writes informal Bahasa Indonesia reply. Saves as `ready_for_review`.
3. **Review** — Human inspects `draft_text`, approves → `approved` or skips → `skipped`.
4. **Post** — Playwright injects saved cookies, types reply in web UI, submits, verifies reply appears in DOM. Marks `posted`. Max 5/day per platform, 90–300s random delays.

## Database (SQLite — single table: `replies`)

Key columns: `id`, `platform` (threads/x), `account_username`, `parent_post_id`, `parent_post_url`, `parent_post_text`, `parent_author`, `draft_text`, `final_text`, `reply_url`, `status`, `error`, `scraped_at`, `drafted_at`, `approved_at`, `posted_at`.

Unique constraint: `(platform, account_username, parent_post_id)`.

**Statuses**: `scraped` → `ready_for_review` → `approved` → `posted` / `failed` / `skipped`

## Key CLI Commands

| Command | Purpose |
|---------|---------|
| `scrape --platform all` | Discover viral posts |
| `queue --status ready_for_review` | Show drafts to review |
| `approve --id N` | Approve a draft |
| `skip --id N` | Reject a draft |
| `post --id N` | Post approved item |
| `status` | Daily counts, queue depth, token expiry |
| `x-login` / `threads-login` | Capture auth cookies via visible browser |

## Brand Config (`brand/brand-profile.json`)

Single source of truth for: voice (operator-grade, calm, anti-hype), keywords to monitor, audience personas (builders + business owners), reply modes (agree_and_extend / polite_contrarian / concrete_example / ask_sharpening_question / translate_to_outcome), char limits (X ≤270, Threads ≤480), and operational caps (5 replies/day, 90–300s delays).

**Never hardcode brand logic in code — always read from this JSON.**

## Tech Stack

Python 3.10+, SQLite, Playwright (Chromium), Anthropic Claude API, httpx, python-dotenv.

**Why Playwright instead of official APIs**: Threads Graph API can't reply to others' posts yet. X/twikit is broken. Browser automation with cookies is the only reliable path.

## Auth

Cookie-based only (no OAuth). Cookies captured via `x-login` / `threads-login` commands (opens visible browser). Stored in `accounts/*.cookies.json` (gitignored). `.env` holds `ANTHROPIC_API_KEY`.

## Hard Rules for Integration

1. Never post without explicit per-item human approval.
2. Brand JSON is the single source of truth — never inline brand logic.
3. Enforce 5 replies/day cap per platform before posting.
4. Random 90–300s delay between posts — never burst.
5. Replies always in informal Bahasa Indonesia (gw/lo register).
6. Verify post success via DOM before marking `posted`.
7. On auth error or 429 — pause platform, notify user. No retry loops.
