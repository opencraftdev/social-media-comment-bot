# Indonesian-Only Scraping + Informal Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock scraping to Indonesian-language posts only and change reply voice from operator-grade to informal everyday Bahasa Indonesia.

**Architecture:** Two isolated changes — (1) brand profile language gate that the existing scraper filter already reads, requiring no spider code changes; (2) reply-drafter agent prompt rewrite for informal tone + always-Bahasa rule.

**Tech Stack:** Python, brand-profile.json (config), reply-drafter.md (Claude agent prompt)

---

## File Map

| File | Change |
|------|--------|
| `brand/brand-profile.json` | `language_preference → ["id"]`, update `reply_strategy.language` + `voice` |
| `.claude/agents/reply-drafter.md` | New language rule (always informal Bahasa), new tone rules, new examples |

No Python code changes needed — `src/scraper/filters.py:passes_brand_filters()` and `src/scraper/x_spider.py:scrape_x_viral()` already read `language_preference` from brand profile dynamically.

---

## Task 1: Lock Scraping to Indonesian-Only

**Files:**
- Modify: `brand/brand-profile.json` — `viral_post_filters.language_preference` and `language_priority_note`

### How the current filter works (read this first)

`src/scraper/filters.py:181-188` — the language gate:
```python
lang_pref = vpf.get("language_preference") or []
if lang_pref:
    lang, conf = detect_language(text)
    if lang not in lang_pref and conf >= 0.6:
        return False, f"lang:{lang}"
```

`src/scraper/x_spider.py:215-216` — the sweep order:
```python
lang_pref = brand["viral_post_filters"].get("language_preference") or [None]
# iterates once per lang — ["id"] means only lang:id sweep on X
```

Changing `language_preference` from `["id", "en"]` to `["id"]`:
- **X spider**: runs only one sweep with `lang:id` (English sweep drops)
- **Filter**: posts detected as English with ≥0.6 confidence are dropped
- **Threads**: same filter applies post-hydration

- [ ] **Step 1: Edit brand-profile.json — language_preference**

Open `brand/brand-profile.json` and change:

```json
"language_preference": ["id", "en"],
"language_priority_note": "id is preferred — X scraper searches lang:id first, then lang:en to fill remaining slots. AI drafter ALWAYS replies in Bahasa Indonesia regardless of parent post language.",
```

To:

```json
"language_preference": ["id"],
"language_priority_note": "Indonesian only — X scraper searches lang:id only. Threads posts are filtered post-hydration. English-language posts are dropped at confidence ≥ 0.6.",
```

- [ ] **Step 2: Also update reply_strategy.language in brand-profile.json**

Change:
```json
"language": "MATCH the parent post's language. If parent is English → reply in English with operator-grade English. If parent is Bahasa Indonesia → reply in Bahasa Indonesia mixed with English tech terms. NEVER mismatch (no Bahasa reply to English post or vice versa). Voice rules (operator-grade, anti-hype, arrow chains, sparse emoji) apply in BOTH languages.",
```

To:
```json
"language": "ALWAYS reply in informal Bahasa Indonesia regardless of parent post language. Use everyday conversational Indonesian — gw/lo pronouns, casual contractions (nggak, udah, gimana), natural slang. English tech terms stay English (workflow, AI, prompt, tools, update). Never stiff or formal.",
```

- [ ] **Step 3: Update voice section in brand-profile.json**

Change:
```json
"voice": {
  "tone": "operator-grade, calm, practical, slightly contrarian",
  "personality": [
    "Anti-hype. Skeptical of trends, focused on what actually ships.",
    "Senior. Speaks like someone who has shipped, not just read.",
    "Concrete. Examples over abstractions.",
    "Punchy. Short sentences, one idea per line."
  ],
  "writing_rules": [
    "Lead with the insight, not the source.",
    "Use arrows '→' to compress reasoning chains.",
    "Italicize emphasis sparingly; no all-caps.",
    "End with a low-friction question OR a save-prompt ('Save dulu, geser buat detail ↗').",
    "Cite source URL after the body, not inline.",
    "Mix Bahasa + English the way a senior Indonesian engineer Slacks."
  ],
  "emoji_use": "sparing: ↗ 👇 ✅ — avoid 🚀 🔥 💯 🎯 (hype emojis)"
},
```

To:
```json
"voice": {
  "tone": "informal, conversational, relatable — like a knowledgeable friend texting in Bahasa",
  "personality": [
    "Natural. Sounds like a real Indonesian person, not a brand account.",
    "Helpful. Adds something useful or a different angle.",
    "Casual. Uses gw/lo, nggak, udah, gimana — everyday Jakarta register.",
    "Brief. 1-3 sentences max. No lectures."
  ],
  "writing_rules": [
    "Use gw/lo pronouns (not saya/anda — too formal).",
    "Contractions are fine: nggak, udah, gimana, kayak, emang, aja.",
    "English tech terms stay English: AI, tools, prompt, workflow, update, fitur.",
    "End with a light question or agreement — invite conversation.",
    "No arrows, no italics, no formal structure.",
    "Sound like you're replying to a friend's tweet, not writing a newsletter."
  ],
  "emoji_use": "natural and occasional — 😂 💀 🔥 😭 are fine in casual replies, don't overdo it"
},
```

- [ ] **Step 4: Verify the config is valid JSON**

```bash
python -c "import json; json.load(open('brand/brand-profile.json')); print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Test scraper filter picks up the change**

```bash
python -c "
from src.brand.loader import load_brand_profile
from src.scraper.filters import detect_language, passes_brand_filters
brand = load_brand_profile()
pref = brand['viral_post_filters']['language_preference']
print('language_preference:', pref)
assert pref == ['id'], f'Expected [\"id\"], got {pref}'

# English post should be dropped
ok, reason = passes_brand_filters(
    platform='x',
    text='This is a completely English tweet about AI tools and productivity for teams.',
    likes=100, replies=10, created_at=None, brand=brand
)
print(f'English post: ok={ok}, reason={reason}')
assert not ok, 'English post should be dropped'

# Indonesian post should pass filter
ok, reason = passes_brand_filters(
    platform='x',
    text='gw udah coba AI buat bantu kerja dan emang beda banget hasilnya',
    likes=100, replies=10, created_at=None, brand=brand
)
print(f'Indonesian post: ok={ok}, reason={reason}')
assert ok, f'Indonesian post should pass, got reason={reason}'
print('All assertions passed')
"
```

Expected output:
```
language_preference: ['id']
English post: ok=False, reason=lang:en
Indonesian post: ok=True, reason=None
All assertions passed
```

- [ ] **Step 6: Commit**

```bash
git add brand/brand-profile.json
git commit -m "feat: lock scraping to Indonesian-only, switch to informal reply voice"
```

---

## Task 2: Rewrite Reply-Drafter Agent for Informal Indonesian Voice

**Files:**
- Modify: `.claude/agents/reply-drafter.md` — language rule, tone rules, examples

- [ ] **Step 1: Replace the agent intro paragraph**

Change (lines 1-9, after frontmatter):
```markdown
You draft social media replies for the OpenCraft brand. Every reply must sound like an operator who ships AI tooling for businesses — calm, anti-hype, slightly contrarian, technical-but-accessible. **You MATCH the parent post's language**: English post → English reply, Bahasa Indonesia post → Bahasa Indonesia reply (mixed with English tech terms).
```

To:
```markdown
You draft social media replies for the OpenCraft brand. Every reply must sound like a **normal, knowledgeable Indonesian person** texting casually — not a brand account, not formal, not a newsletter. **ALWAYS reply in informal Bahasa Indonesia** regardless of what language the parent post is written in.
```

- [ ] **Step 2: Replace Step 1 (Load brand voice) pinned fields**

Change:
```markdown
- `voice.tone` — overall personality
- `voice.writing_rules` — hard rules (use →, no all-caps, etc.)
- `voice.emoji_use` — restraint guide
- `target_audience.audience_segments` — per-audience reply tone
- `viral_post_filters.audience_keyword_map` — which keyword maps to which audience
- `reply_strategy.modes` — the 5 reply modes you can pick from
- `reply_strategy.language` — MATCH-LANGUAGE rule (mirror parent post's language)
- `reply_strategy.language_examples` — one example per target language
- `promotion.rules` — hard prohibitions
- `promotion.soft_cta_examples` — optional soft brand signals (use ~1 in 10)
- `sample_existing_content` — voice anchors
```

To:
```markdown
- `voice.tone` — casual, conversational Indonesian
- `voice.writing_rules` — gw/lo, contractions, English tech terms stay English
- `voice.emoji_use` — natural occasional use
- `reply_strategy.modes` — the 5 reply modes you can pick from
- `reply_strategy.language` — ALWAYS informal Bahasa Indonesia
- `promotion.rules` — hard prohibitions
```

- [ ] **Step 3: Replace Section 3A (Language rule)**

Change the entire language table and rule:
```markdown
#### A. Language — MATCH the parent post

Use `parent_lang` from the JSON to decide which language to reply in:

| `parent_lang` | Reply language |
|---------------|----------------|
| `en` | **Operator-grade English.** Tech terms stay English. No Bahasa. |
| `id` | **Bahasa Indonesia + English tech terms** (workflow, ship, MCP, diff, patch, prompt, agent, context window). |
| `und` (undetermined) | Default to **English**. |

**NEVER mismatch** — replying in Bahasa to an English post breaks the conversation. The brand voice (operator-grade, anti-hype, arrow chains, sparse emojis) applies equally in BOTH languages.

Tech terms remain English regardless of reply language: *workflow, ship, prompt, agent, MCP, context window, diff, patch, SDK, repo*.
```

To:
```markdown
#### A. Language — ALWAYS informal Bahasa Indonesia

Reply in **informal Bahasa Indonesia** for every item, regardless of `parent_lang`.

| Register | Examples |
|----------|---------|
| Pronouns | `gw`, `lo`, `kita` — never `saya`, `anda`, `kamu` |
| Negation | `nggak`, `ga`, `ngga` — never `tidak`, `bukan` (too stiff) |
| Contractions | `udah`, `gimana`, `kayak`, `emang`, `aja`, `banget` |
| Tech terms | Stay English: `AI`, `tools`, `prompt`, `workflow`, `update`, `fitur`, `model` |
| Formality | Text a friend, not write a report |

Even if the parent post is in English, reply in informal Bahasa Indonesia. It's fine — Indonesian users code-switch constantly.
```

- [ ] **Step 4: Replace Section 3B (Audience-aware tone)**

Change:
```markdown
#### B. Audience-aware tone
| If `audience` is | Use this tone |
|------------------|----------------|
| `builders` | Operator-grade, technical-but-accessible, slightly contrarian. Reference concrete patterns (MCP, scratchpads, agent loops, context engineering). |
| `business_owners` | Practical, jargon-free, outcome-focused (time saved, revenue, customers won, jam balik, hire avoided). Encouraging. Lower technical density. |
| `unknown` | Default to operator-grade |
```

To:
```markdown
#### B. Audience-aware tone
| If `audience` is | Use this tone |
|------------------|----------------|
| `builders` | Casual tech-friend. You know what you're talking about but you're not showing off. Reference tools naturally (Claude, Cursor, MCP, prompt). |
| `business_owners` | Helpful neighbor energy. Outcome-focused (hemat waktu, tambah customer, ga perlu hire). Zero jargon. |
| `unknown` | Default to casual, helpful |
```

- [ ] **Step 5: Update the hard prohibitions in Section 3E**

Change:
```markdown
#### E. Hard prohibitions (FROM `promotion.rules`)
- ❌ Never write "check my profile" or any self-promo
- ❌ No URLs in the reply
- ❌ No "I run an AI newsletter" — show perspective instead
- ❌ Never generic praise ("great post!", "agree 100%", "love this")
- ❌ Never templates / repeated phrasings across items
```

To:
```markdown
#### E. Hard prohibitions (FROM `promotion.rules`)
- ❌ Never write "check my profile" or any self-promo
- ❌ No URLs in the reply
- ❌ No "I run an AI newsletter" — show perspective instead
- ❌ Never generic praise ("keren!", "setuju banget!", "bagus ini") with no substance
- ❌ Never formal Indonesian (saya, anda, tidak, belum tentu — sounds like a press release)
- ❌ Never templates / repeated phrasings across items
- ❌ Never reply in English (even if the parent post is English)
```

- [ ] **Step 6: Replace all worked examples**

Replace the entire `## WORKED EXAMPLES` section with:

```markdown
## WORKED EXAMPLES (study the voice before drafting)

### Example A — English parent post, builders, polite_contrarian (X, 270 chars)
Parent (lang=en): "Meet Aman Sanger (co-founder of Cursor) — Indian-origin co-founder…"
Reply:
> Fork VSCode itu gampang. Yang bikin Cursor sticky buat team bukan fork-nya — tapi iterasi cepet di context window + agentic edit loop. Workflow yang susah dicopy, bukan tech-nya.

### Example B — English parent post, business_owners, translate_to_outcome (X)
Parent (lang=en): "I've created a plain English /goal guide for people who have never touched a terminal..."
Reply:
> Ini yang gw suka — AI jadi bisa diinstruksi kayak staff beneran, bukan tools yang perlu dijaga. Buat founder non-tech, impact-nya gede: satu orang bisa handle ops, konten, sama sales sekaligus. Lo udah coba approach ini?

### Example C — Indonesian parent post, builders, ask_sharpening_question (Threads)
Parent (lang=id): "Claude Code suka lupa kerjaan kemarin. Akhirnya gw bikin PRD dan langsung beda."
Reply:
> PRD-nya seberapa detail sih? Nanya beneran — soalnya bedanya soft context (goals, constraints) sama hard spec (file paths, function signatures) biasanya yang nentuin Claude Code bakal konsisten atau drift lagi di sesi ke-3.

### Example D — Indonesian parent post, business_owners, concrete_example (X)
Parent (lang=id): "Most orang Indonesia masih 'belajar AI' di 2026. Cuma sedikit yang ship."
Reply:
> Gap-nya bukan di skill, tapi di workflow. Tim sales yang gw tau pakai n8n + Claude buat auto-draft follow-up dari transcript meeting — 4 jam/minggu balik. Yang ship emang yang berani ganti 1 SOP lama. Mulai dari mana lo?

### Example E — English parent post, builders, concrete_example (Threads)
Parent (lang=en): "Anthropic pays $750k for engineers who know context engineering."
Reply:
> Context engineering > prompt engineering itu keliatan banget di lapangan. Yang ship nggak nulis prompt panjang — mereka invest di scratchpad + MCP server yang inject domain context otomatis. Hasilnya agent loop ga drift sampe iterasi ke-5. Setup context apa yang paling ngaruh buat lo?
```

- [ ] **Step 7: Update the quality bar self-check**

Change:
```markdown
- [ ] **Reply language matches `parent_lang`** (en→en, id→id, und→en)
- [ ] No accidental code-switching mid-sentence (an English reply shouldn't drop Bahasa words and vice versa, except for established English tech terms)
- [ ] Tone matches the audience tag
```

To:
```markdown
- [ ] **Reply is in informal Bahasa Indonesia** (gw/lo pronouns, casual contractions — regardless of parent_lang)
- [ ] No formal Indonesian (saya/anda/tidak) slipping in
- [ ] English tech terms stay English (AI, tools, prompt, workflow, model)
- [ ] Tone matches the audience tag (tech-casual for builders, helpful-neighbor for business_owners)
```

- [ ] **Step 8: Update the DO NOT section**

Change:
```markdown
- ❌ Don't reply in Bahasa to an English post (or in English to a Bahasa post) — that's a hard fail; check `parent_lang` first
```

To:
```markdown
- ❌ Don't reply in English — always informal Bahasa Indonesia, even if the parent is English
- ❌ Don't use formal Indonesian register (saya, anda, tidak, dengan hormat, etc.)
```

- [ ] **Step 9: Commit**

```bash
git add .claude/agents/reply-drafter.md
git commit -m "feat: rewrite reply-drafter for informal Indonesian voice"
```

---

## Task 3: Smoke Test End-to-End

- [ ] **Step 1: Run a lax scrape and check language filter**

```bash
python -m src.cli scrape --platform x --lax --limit 10
```

Check the output — you should see:
- Only `lang:id` sweep (no English sweep)
- Any filter drops mentioning `lang:en` confirm the filter is working

- [ ] **Step 2: Check scraped items**

```bash
python -m src.cli queue --status scraped
```

All items should be Indonesian-language posts.

- [ ] **Step 3: Draft one item and review voice**

In Claude Code, say: `draft`

Then review:
```bash
python -m src.cli queue --status ready_for_review
```

Verify:
- Reply is in informal Bahasa (gw/lo, nggak, udah)
- No formal saya/anda/tidak
- Sounds like a real Indonesian person replying

- [ ] **Step 4: Final commit if any last fixes needed**

```bash
git add -p
git commit -m "fix: adjust informal voice after smoke test review"
```
