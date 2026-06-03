"""Loads brand profile from Supabase brand_profile table (single row, slug='opencraft').
Falls back to local brand/brand-profile.json if Supabase env vars are not set.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

BRAND_PROFILE_PATH = Path(__file__).resolve().parents[2] / "brand" / "brand-profile.json"


def load_brand_profile() -> dict:
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    if supabase_url and supabase_key:
        from supabase import create_client
        db = create_client(supabase_url, supabase_key)
        res = db.from_("brand_profile").select("data").eq("slug", "opencraft").single().execute()
        return res.data["data"]

    # Fallback: local JSON (for dev without Supabase)
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
