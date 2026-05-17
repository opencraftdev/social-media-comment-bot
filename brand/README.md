# OpenCraft Brand Profile

> Generated from Zernio API on 2026-05-17 by analyzing 3 connected accounts and recent published posts.

## TL;DR — The Brand

**OpenCraft** is daily AI news, **read like an operator**.

- Anti-hype. Watches **what ships**, not what trends.
- Operator-grade voice — senior, concrete, slightly contrarian.
- Bahasa Indonesia + English tech terms.
- Beat: Claude Code, MCP, agentic dev tools, AI rollout in teams.

## Connected Accounts

| Platform | Handle | URL | Followers (at gen) |
|----------|--------|-----|---------------------|
| Instagram | `@opencraft.dev` | https://instagram.com/opencraft.dev | 2 |
| Threads | `@opencraft.dev` | https://threads.net/@opencraft.dev | 0 |
| X / Twitter | `@opencraftdev` | https://x.com/opencraftdev | 1 |

All under Zernio profile **"Default"** (`6a07641e3f2fdcee58b27f70`).

## Files

| File | Purpose |
|------|---------|
| [brand-profile.json](./brand-profile.json) | Machine-readable brand profile — fed into the AI comment generator |
| [README.md](./README.md) | Human-readable summary (this file) |

## How the Brand Profile Was Built

```
1. Zernio API → GET /profiles            → got "Default" profile
2. Zernio API → GET /accounts            → 3 platforms: IG, Threads, X
3. Zernio API → GET /posts?status=published → recent post content
4. Analyzed:
   - Bios across 3 platforms (consistent positioning)
   - Recent post copy (voice, language mix, structure)
   - Hashtag/tag usage (zero — fully editorial style)
   - Subjects covered (AI dev tools, workflow, shipping)
5. Synthesized → brand-profile.json
```

## What Drives Every AI-Generated Reply

When the bot drafts a reply to a viral post, it loads `brand-profile.json` and applies:

| Field | Effect on Reply |
|-------|-----------------|
| `voice.tone` | Sets the writing personality |
| `voice.writing_rules` | Hard rules (no all-caps, use →, etc.) |
| `target_audience.language_mix` | Bahasa-primary, English tech terms |
| `niche.subtopics` | Validates if a post is on-brand |
| `niche.anti_topics` | Auto-skips off-brand viral posts |
| `promotion.rules` | Prevents spammy "check my profile" patterns |
| `promotion.soft_cta_examples` | Optional brand signals (~1 in 10 replies) |
| `reply_strategy.modes` | Rotates: agree-extend / contrarian / example / question |
| `viral_post_filters` | Discovery layer: which posts to surface |

## Why This Works (Brand Theory)

> "Brand-by-presence" — be consistently insightful in the right rooms, and the brand grows because people start associating your handle with operator-grade AI takes. No link drops needed.

## Tweaks Recommended

A few things to confirm or adjust before going live:

1. **Promotion intensity** — Currently set to "value-first, soft mention ~1 of 10 replies". Want it higher (every reply) or lower (pure value, never mention OpenCraft)?
2. **Indonesian-English mix** — Bot will default to Bahasa-primary with English tech terms. Want pure English on X (broader reach) vs Bahasa-only on Threads (matches existing voice)?
3. **Keyword list** — `viral_post_filters.monitor_keywords` is my guess from your bios. Add/remove anything?
4. **Reply caps** — Set to 5/day per platform. Conservative for new accounts. Bump to 8/day after week 2?
5. **Approval mode** — Recommend semi-auto (you approve each reply) for the first 2 weeks, then evaluate.

## Updating the Brand Profile

When the brand evolves (new product, niche shift), re-run:

```bash
# Pseudo-CLI we'll build:
python -m src.brand.refresh --from-zernio
```

This re-fetches Zernio data + re-analyzes + writes a new `brand-profile.json` (versioned, old kept as `brand-profile.v1.json` etc.).

## Privacy / Security Note

The Zernio API key used to generate this is currently shared in chat history — **rotate it** at zernio.com → API settings. Future fetches should pull from `.env` (gitignored).
