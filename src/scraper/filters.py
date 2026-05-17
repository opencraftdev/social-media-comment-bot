"""Brand-aware filters shared across scrapers.

Every filter reads its thresholds from brand/brand-profile.json. No magic numbers
in the spiders themselves — change behavior by editing the brand profile.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable

try:
    from langdetect import detect_langs, DetectorFactory
    DetectorFactory.seed = 0
    _LANGDETECT_OK = True
except ImportError:
    _LANGDETECT_OK = False


# Distinctively Indonesian function words and slang — NOT shared with Malay.
# Hitting any of these strongly suggests Bahasa Indonesia (not Malay/Tagalog).
_ID_STRONG = {
    # Jakarta/informal pronouns (not used in Malay)
    "gw", "gue", "gua", "lo", "lu", "elu", "loe", "elo",
    # Common ID slang/intensifiers (Malay uses different equivalents)
    "banget", "gokil", "anjir", "anjay", "kuy", "asik", "asyik", "santuy",
    # ID-specific particles
    "dong", "deh", "sih", "kok", "nih", "tuh", "yak",
    # ID-specific negation
    "nggak", "ngga", "ga", "kagak",
    # ID-specific conjunctions / fillers
    "udah", "udeh", "gimana", "bagaimana", "kayak", "kayaknya", "soalnya",
    "sebenarnya", "ternyata", "padahal", "makanya", "emang", "memang",
    "bener", "betul", "trus", "terus", "abis", "habis",
    "kalo", "kalau",
}

# Shared with Malay — count but with lower weight (1 hit alone isn't enough)
_ID_SHARED = {
    "yang", "untuk", "dengan", "dari", "pada", "ini", "itu", "saya", "kami",
    "kita", "kamu", "anda", "mereka", "dia", "akan", "sudah", "belum", "juga",
    "tapi", "atau", "dan", "ke", "oleh", "dalam", "atas", "antara", "hingga",
    "sampai", "sejak", "ketika", "jika", "walau", "bisa", "harus", "buat",
    "bikin", "pakai", "kasih", "aja", "lagi", "biar", "supaya", "karena",
    "yaitu", "yakni", "bahwa", "agar",
}

# Words that strongly suggest Malay (Bahasa Melayu), NOT Indonesian
_MS_MARKERS = {
    "macam", "tak", "takyah", "tgk", "leh", "boleh", "ialah", "lah",
    "kau", "korang", "weh", "wei", "x", "je", "saje", "sahaja", "bwlek",
    "ye", "nak", "tanak", "takde", "ade", "ape", "camne", "macamne",
    "ape", "punye", "kite", "diorang",
}

_ID_MARKERS = _ID_STRONG | _ID_SHARED

_WORD_SPLIT = re.compile(r"[\w']+", re.UNICODE)


def _count_markers(text: str, markers: set[str]) -> int:
    tokens = [t.lower() for t in _WORD_SPLIT.findall(text)]
    return sum(1 for t in tokens if t in markers)


def detect_language(text: str) -> tuple[str, float]:
    """Hybrid language detector tuned for short Indonesian+English tech posts.

    Returns (lang_code, confidence_0_to_1).

    Logic:
      1. Distinctively-Malay markers (`tak`, `macam`, `leh` etc.) → 'ms'.
      2. Indonesian-only slang (`gw`, `banget`, `dong`, `nggak`) → confident 'id'.
      3. ≥2 shared Indo/Malay markers WITHOUT Malay-specific → 'id'.
      4. Else fall back to langdetect.
    """
    if not text or len(text.strip()) < 8:
        return "und", 0.0

    ms_hits = _count_markers(text, _MS_MARKERS)
    id_strong_hits = _count_markers(text, _ID_STRONG)
    id_shared_hits = _count_markers(text, _ID_SHARED)

    # Malay distinguishing markers win immediately (don't let id_shared pull it back)
    if ms_hits >= 1 and id_strong_hits == 0:
        return "ms", min(1.0, 0.6 + 0.15 * ms_hits)

    # Clear Indonesian slang signal
    if id_strong_hits >= 1:
        return "id", min(1.0, 0.7 + 0.1 * id_strong_hits)

    # Shared-only signal: need at least 2 hits AND no Malay markers to call it 'id'
    if id_shared_hits >= 2 and ms_hits == 0:
        return "id", min(1.0, 0.55 + 0.08 * id_shared_hits)

    if _LANGDETECT_OK:
        try:
            top = detect_langs(text)[0]
            return top.lang, float(top.prob)
        except Exception:
            pass

    return "und", 0.0


def _contains_any(text: str, needles: Iterable[str]) -> str | None:
    low = text.lower()
    for n in needles:
        if n.lower() in low:
            return n
    return None


def _own_handles(brand: dict) -> set[str]:
    """All handles owned by the brand — normalized lowercase, no @."""
    handles: set[str] = set()
    for acct in (brand.get("accounts") or {}).values():
        h = (acct.get("username") or "").lstrip("@").lower()
        if h:
            handles.add(h)
    return handles


def passes_brand_filters(
    *,
    platform: str,
    text: str,
    likes: int,
    replies: int,
    created_at: datetime | None,
    brand: dict,
    author: str | None = None,
) -> tuple[bool, str | None]:
    """Returns (kept, reason_dropped_if_any).

    Filters applied (in order, short-circuits):
      1. self_handle            — never reply to our own posts across any account
      2. anti_topics            — drop if any anti_topic substring present
      3. skip_if_post_contains  — drop spammy markers (giveaways, NFT mint, etc.)
      4. min_engagement         — per-platform like/reply thresholds
      5. max_post_age_hours     — drop posts older than threshold (skipped if no ts)
    """
    vpf = brand.get("viral_post_filters", {})
    niche = brand.get("niche", {})

    # 1. self-skip
    if author and author.lstrip("@").lower() in _own_handles(brand):
        return False, "self_handle"

    # 2. anti-topics
    anti_topics = niche.get("anti_topics", []) or []
    hit = _contains_any(text, anti_topics)
    if hit:
        return False, f"anti_topic:{hit}"

    # 3. spam markers
    skip_words = vpf.get("skip_if_post_contains", []) or []
    hit = _contains_any(text, skip_words)
    if hit:
        return False, f"skip_word:{hit}"

    # 4. engagement
    min_eng = (vpf.get("min_engagement") or {}).get(platform) or {}
    min_likes = int(min_eng.get("min_likes", 0))
    min_replies = int(min_eng.get("min_replies", 0))
    if likes < min_likes:
        return False, f"likes<{min_likes}"
    if replies < min_replies:
        return False, f"replies<{min_replies}"

    # 5. age
    max_hours = vpf.get("max_post_age_hours")
    if max_hours and created_at:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - created_at
        if age > timedelta(hours=int(max_hours)):
            return False, f"age>{max_hours}h"

    # 6. language
    lang_pref = vpf.get("language_preference") or []
    if lang_pref:
        lang, conf = detect_language(text)
        # Be lenient: allow if detected lang is in preference OR low confidence
        if lang not in lang_pref and conf >= 0.6:
            return False, f"lang:{lang}"

    return True, None
