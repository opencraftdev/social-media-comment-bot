---
name: social-bot
description: OpenCraft social reply bot — end-to-end workflow for scraping viral posts on Threads (Playwright) and X (twikit), drafting brand-aware replies via Claude API, managing approval queue, and posting via official APIs. Triggers on full daily run, complete cycle, end-to-end, today's run, daily routine, sync everything.
---

# Social Bot — Full Workflow Skill

> Loaded when the user wants an end-to-end run. For single commands, see [CLAUDE.md](../../../CLAUDE.md) trigger map.

## Mission

Run the daily OpenCraft engagement cycle: discover viral posts → draft brand-aware replies → present approval queue → post approved items with anti-ban pacing.

## Preflight Checklist (Run Before Any Step)

```bash
python -m src.cli status          # daily reply quota, queue depths
python -m src.cli scrapers        # scraper health: cookies, last run, brand config
python -m src.cli scrapers --probe  # live Playwright probe of X session (slower)
```

Verify:

- [ ] X cookies file exists with required keys (`auth_token`, `ct0`) — `scrapers` shows this
- [ ] If X cookies are stale (login wall on probe) → run `python -m src.cli x-login`
- [ ] Threads access token present in `.env`
- [ ] Daily reply count is under cap (Threads ≤5, X ≤5)
- [ ] No `failed` items from last cycle requiring investigation
- [ ] Brand profile loads cleanly: `python -m src.cli brand-show`

If anything fails, **stop and report to user** — don't auto-fix.

## Daily Cycle — Steps

### 1. Discovery (Scrape)

```bash
python -m src.cli scrape --platform threads --limit 30
python -m src.cli scrape --platform x --limit 30
# Or both:
python -m src.cli scrape --platform all --limit 30
# Add --lax to disable engagement+age filters (testing only):
python -m src.cli scrape --platform all --limit 30 --lax
```

What happens (both scrapers, identical filter pipeline):

- **Threads**: Playwright opens public search SERP per keyword, then hydrates each post page to extract text + engagement
- **X**: Playwright opens authenticated search via your cookies, scrapes tweet cards via `data-testid` selectors
- Filters in order (all from `brand/brand-profile.json`):
  1. **self_handle** — never scrape our own accounts
  2. `anti_topics` — drop matches like crypto/AGI hype
  3. `skip_if_post_contains` — spam markers (giveaway, NFT mint, etc.)
  4. `min_engagement` per platform (Threads ≥30♥, X ≥50♥/5💬)
  5. `max_post_age_hours` (default 6h) — needs timestamp
- Dedup: UNIQUE constraint on `(platform, account, parent_post_id)`
- Writes new items as `status=scraped` (then `draft_pending` once drafter exists)
- Persists `parent_created_at` for age-filter audits

Report counts to user:

```
Scraped: Threads 8 candidates, X 12 candidates
After filters: Threads 3 kept, X 5 kept
After dedup: Threads 3 new, X 4 new
```

### 2. AI Drafting

```bash
python -m src.cli draft --limit 5 --platform all
```

What happens per item:
- Loads `brand/brand-profile.json`
- Loads `parent_post_text` from queue
- Selects reply mode (rotates through `reply_strategy.modes`)
- Calls Claude API with brand-conditioned prompt
- Validates: length ≤ platform max, no banned phrases, no URLs
- Writes draft → `status=ready_for_review`

If validation fails twice, mark `status=skipped` with reason.

### 3. Show Approval Queue

```bash
python -m src.cli queue --status ready_for_review
```

Display each item in compact form:

```
[42] threads · @author · 12 min ago · 340♥
   "AI agents are overrated, here's why..."

   Draft (mode: polite_contrarian):
   "Setuju di permukaan — tapi 6 bulan terakhir latency agent
    turun 10x. Yang 'overrated' itu asumsi perf 2024. Game-nya
    udah ganti → tooling, bukan model."

   Approve? [a]pprove · [e]dit · [s]kip
```

Walk through items with the user. Do NOT post yet.

### 4. Post Approved (Throttled)

```bash
python -m src.cli post --all-approved
```

What happens:
- Posts in order of approval timestamp
- Random delay 90-300s between each post (enforced by CLI)
- Threads: 2-step (create container → publish) via official API
- X: single `create_tweet(reply_to=...)` via twikit
- On 429/auth error: pause that platform 1h, report to user

Report:

```
Posted: 3/3 Threads, 2/2 X
Failures: 0
Daily count: Threads 3/5, X 2/5
```

### 5. Wrap-up Status

```bash
python -m src.cli status
```

## Error Handling Rules

| Error | Response |
|-------|----------|
| Playwright timeout on scrape | Skip that keyword, log, continue |
| twikit `TooManyRequests` | Pause X 30 min, report |
| Threads API quota check shows ≥ cap | Skip posting for that account today |
| Claude API rate limit during draft | Backoff 60s, retry once, then skip item |
| Dedup conflict during post | Mark `skipped`, do not re-post |
| Token expired | Stop, report to user — never auto-refresh in skill flow |

## Forbidden in Skill Mode

- ❌ Auto-posting without showing the queue to the user first
- ❌ Bypassing `operational_caps` from the brand profile
- ❌ Using anything other than the brand profile for voice
- ❌ Posting to Instagram (we only post via Zernio manually)
- ❌ Adding new platforms without explicit user approval

## When to Invoke a Subagent

If a draft needs **multi-round refinement** (e.g., the user says "make it sharper" 3 times), consider delegating to an Explore or general-purpose subagent to A/B variants — but ONLY when explicitly asked. Default: draft, present, accept feedback.

## When to Bail Out

Stop the cycle and surface to the user if:

- More than 30% of scraped items fail brand filtering (means keywords need tuning)
- More than 1 platform has token issues (means setup work needed)
- Draft quality looks templated/repetitive across 3+ items (means brand prompt is degrading)

## Brand Profile Reload

If the user updates `brand/brand-profile.json` mid-session, run:

```bash
python -m src.cli brand-show
```

to confirm new values are read. Then re-draft any pending items.

## Notes for Claude

- Read [CLAUDE.md](../../../CLAUDE.md) for the natural-language trigger map.
- Read [brand/brand-profile.json](../../../brand/brand-profile.json) before any AI step.
- Read [brand/README.md](../../../brand/README.md) for human-readable brand context.
- See [docs/threads-api-docs/](../../../docs/threads-api-docs/) and [docs/x-twikit-docs/](../../../docs/x-twikit-docs/) for API details.
