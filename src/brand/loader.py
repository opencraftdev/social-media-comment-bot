"""Loads brand/brand-profile.json. Single source of truth for brand voice."""
from __future__ import annotations

import json
from pathlib import Path

BRAND_PROFILE_PATH = Path(__file__).resolve().parents[2] / "brand" / "brand-profile.json"


def load_brand_profile() -> dict:
    with BRAND_PROFILE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def summarize_brand(brand: dict) -> dict:
    return {
        "brand_name": brand["brand_name"],
        "tagline": brand["tagline"],
        "accounts": {k: v["username"] for k, v in brand["accounts"].items()},
        "niche_primary": brand["niche"]["primary"],
        "voice_tone": brand["voice"]["tone"],
        "monitor_keywords_count": len(brand["viral_post_filters"]["monitor_keywords"]),
        "caps": brand["operational_caps"]["replies_per_day"],
    }
