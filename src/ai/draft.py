"""Programmatic drafting via Claude API — mirrors the reply-drafter subagent logic."""
from __future__ import annotations

import json
import logging
import os
from itertools import cycle

import anthropic

from src.brand.loader import load_brand_profile
from src.queue.db import init_db, list_items, save_draft, mark_draft_failed
from src.scraper.filters import detect_language

log = logging.getLogger(__name__)

REPLY_MODES = [
    "agree_and_extend",
    "polite_contrarian",
    "concrete_example",
    "ask_sharpening_question",
    "translate_to_outcome",
]

SYSTEM_PROMPT = """\
Kamu adalah OpenCraft — akun media sosial yang reply ke postingan viral tentang AI, tools, dan agentic development.

Setiap reply HARUS dalam Bahasa Indonesia informal (register gw/lo), tanpa pengecualian.
Bahkan kalau postingan aslinya dalam English, reply tetap dalam Bahasa Indonesia informal.

Aturan ketat:
- Pronoun: gw, lo, kita — BUKAN saya, anda, kamu
- Negasi: nggak, ga, ngga — BUKAN tidak, bukan
- Kontraksi: udah, gimana, kayak, emang, aja, banget
- Tech terms tetap English: AI, tools, prompt, workflow, model, update, fitur, MCP, agent
- JANGAN self-promo atau sebut "check my profile"
- JANGAN URL di reply
- JANGAN generik ("keren!", "setuju banget!" tanpa substansi)
- JANGAN end dengan pertanyaan — tutup dengan opini atau observasi
- JANGAN hashtag
- JANGAN emoji hype: 🚀 🔥 💯 🎯
- Boleh emoji wajar: ↗ 👇 ✅

Format output: hanya teks reply, tidak perlu penjelasan atau prefix apapun.
"""


def _audience_for(note: str | None, brand: dict) -> str:
    kw = (note or "").replace("keyword=", "").strip().lower()
    audience_map = brand.get("viral_post_filters", {}).get("audience_keyword_map", {}) or {}
    for aud, kws in audience_map.items():
        if kw in {k.lower() for k in kws}:
            return aud
    return "unknown"


def _build_user_prompt(item: dict, mode: str, audience: str, platform: str) -> str:
    max_chars = 270 if platform == "x" else 480
    char_guidance = (
        f"Target 200-250 karakter, HARD MAX {max_chars} karakter. Hitung dengan teliti."
        if platform == "x"
        else f"Maksimal {max_chars} karakter, 1-4 kalimat."
    )

    audience_guidance = {
        "builders": "Tone: teman tech kasual. Lo tau yang lo omongin tapi ga sok. Sebut tools secara natural (Claude, Cursor, MCP, prompt).",
        "business_owners": "Tone: tetangga helpful. Fokus ke outcome (hemat waktu, tambah customer, ga perlu hire). Zero jargon.",
        "unknown": "Tone: kasual, helpful.",
    }.get(audience, "Tone: kasual, helpful.")

    mode_guidance = {
        "agree_and_extend": "Mode: setuju dulu, lalu tambah detail operator-level yang belum mereka sebut.",
        "polite_contrarian": "Mode: sudut pandang berbeda, didukung pengalaman shipping — bukan sekadar kontra.",
        "concrete_example": "Mode: drop contoh nyata workflow/pattern yang buktiin poin mereka (atau poin lo).",
        "ask_sharpening_question": "Mode: tanya satu pertanyaan yang bikin ide aslinya lebih konkret. Tapi tutup dengan observasi, BUKAN pertanyaan.",
        "translate_to_outcome": "Mode: translate klaim teknikal ke business outcome yang konkret.",
    }.get(mode, "Mode: agree and extend.")

    return f"""{mode_guidance}
{audience_guidance}
{char_guidance}

Platform: {platform}
Postingan yang di-reply (dari @{item.get("parent_author", "?")}):
---
{item.get("parent_post_text", "")}
---

Tulis reply sekarang. Output hanya teks reply saja."""


def draft_items(platform: str = "all", limit: int = 10) -> dict:
    """
    Draft all pending scraped items via Claude API.
    Returns a summary dict: {"drafted": N, "failed": N, "items": [...]}
    """
    from dotenv import load_dotenv
    load_dotenv()

    init_db()
    brand = load_brand_profile()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    query_platform = None if platform == "all" else platform
    items = list_items(status="scraped", platform=query_platform, limit=limit)

    if not items:
        log.info("No scraped items to draft.")
        return {"drafted": 0, "failed": 0, "items": []}

    log.info("Drafting %d item(s) for platform=%s", len(items), platform)

    mode_cycle = cycle(REPLY_MODES)
    drafted = 0
    failed = 0
    results = []

    for item in items:
        item_id = item["id"]
        item_platform = item["platform"]
        mode = next(mode_cycle)
        audience = _audience_for(item.get("note"), brand)
        max_chars = 270 if item_platform == "x" else 480

        try:
            user_prompt = _build_user_prompt(item, mode, audience, item_platform)

            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            draft_text = response.content[0].text.strip()

            # Validate length
            if len(draft_text) > max_chars:
                # One retry with explicit char count in prompt
                log.warning("Draft #%d too long (%d chars), retrying…", item_id, len(draft_text))
                retry_prompt = user_prompt + f"\n\nDraft sebelumnya terlalu panjang ({len(draft_text)} karakter). Tulis ulang, WAJIB di bawah {max_chars} karakter."
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=300,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": retry_prompt}],
                )
                draft_text = response.content[0].text.strip()

            if len(draft_text) > max_chars:
                reason = f"still too long after retry ({len(draft_text)} chars, max {max_chars})"
                mark_draft_failed(item_id, reason)
                log.warning("Draft #%d failed: %s", item_id, reason)
                failed += 1
                results.append({"id": item_id, "status": "failed", "reason": reason})
                continue

            save_draft(item_id, mode, draft_text)
            log.info("Draft #%d saved (mode=%s, %d chars)", item_id, mode, len(draft_text))
            drafted += 1
            results.append({"id": item_id, "status": "drafted", "mode": mode, "chars": len(draft_text)})

        except Exception as e:
            mark_draft_failed(item_id, str(e)[:500])
            log.error("Draft #%d error: %s", item_id, e)
            failed += 1
            results.append({"id": item_id, "status": "failed", "reason": str(e)})

    log.info("Drafting complete: %d drafted, %d failed", drafted, failed)
    return {"drafted": drafted, "failed": failed, "items": results}
