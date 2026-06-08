"""Tier feature-gating for the chart/data blocks (server-side enforcement).

The reading *sections* are gated in the pipeline (report_sections ∩ tier.sections).
The non-section chart data (divisional vargas, the Jaimini/KP/numerology/transit
tables, Varshphal) is gated here by stripping blocks the tier does not include
*before* they leave the API, so a locked feature cannot be reached by calling the
endpoint directly. The frontend additionally hides/locks them, but the server is
the source of truth.

Note: planet positions (chart["chart"]["planets"]) are NEVER stripped, the D1
birth chart (a free feature) is drawn from them; the *planetary table* is gated
on the client by the "tables_basic" capability instead (the same data is already
visible on the free D1 diagram, so there is nothing to protect server-side).
"""
from __future__ import annotations

import re
from typing import Any

# blocks unlocked only by the "tables_full" capability (Pro+)
_FULL_TABLE_BLOCKS = (
    "jaimini_karakas", "kp_significators", "numerology",
    "yogi_avayogi", "bhrigu_bindu", "double_transit", "sade_sati",
)
# core placements + metadata the D1 charts and anchor always need (every tier)
_ALWAYS = ("engine", "chart", "input", "datetime")


def filter_chart_for_features(chart: dict, features: set[str] | frozenset[str]) -> dict[str, Any]:
    """ALLOW-LIST the chart by tier: return ONLY the blocks the tier's UI uses, so
    no extra interpretive engine output (yogas, shadbala, ashtakavarga, sahams,
    aspects, etc.) is ever exposed over the wire to a tier that didn't unlock it."""
    if not isinstance(chart, dict):
        return chart
    out = {k: chart[k] for k in _ALWAYS if k in chart}      # placements for D1 + anchor (all tiers)

    if "divisional" in features and "vargas" in chart:
        out["vargas"] = chart["vargas"]                     # D9/D10/D24 (Pro)

    if "tables_full" in features:
        for k in _FULL_TABLE_BLOCKS:
            if k in chart:
                out[k] = chart[k]
        if isinstance(chart.get("dasha_systems"), dict):
            out["dasha_systems"] = chart["dasha_systems"]   # all dasha systems (Pro)
    elif "tables_basic" in features:
        ds = chart.get("dasha_systems")
        if isinstance(ds, dict) and "vimshottari" in ds:
            out["dasha_systems"] = {"vimshottari": ds["vimshottari"]}  # Basic: Vimshottari only

    return out


def section_categories(section_keys) -> set[str]:
    """The Finding categories that belong to a set of unlocked section keys."""
    from .llm import SECTION_SPEC  # lazy: avoid import cycle at module load
    keys = set(section_keys or ())
    cats: set[str] = set()
    for key, _title, cs in SECTION_SPEC:
        if key in keys:
            cats.update(cs)
    return cats


# Evidence fragments that belong to paid capabilities. Stripped from findings for
# tiers that lack the feature, so e.g. a Basic user's relationship finding can't leak
# its Navamsa/KP sub-lord facts into chat or the reading.
_DIVISIONAL_RE = re.compile(r"navamsa|dasamsa|vargottama|\bD9\b|\bD10\b|\bD-?\d{1,2}\b", re.IGNORECASE)
_KP_RE = re.compile(r"\bKP\b|sub-?lord", re.IGNORECASE)
_AV_RE = re.compile(r"ashtakavarga|\bbindus?\b|\bSAV\b|\bBAV\b", re.IGNORECASE)


def _strip_evidence(ev, features) -> list:
    """Drop tier-locked fact fragments from an evidence list. Each evidence string
    is segmented on '; '; segments naming a locked capability are removed."""
    feats = set(features or ())
    out = []
    for line in ev or []:
        segs = []
        for seg in str(line).split("; "):
            if "divisional" not in feats and _DIVISIONAL_RE.search(seg):
                continue
            if "tables_full" not in feats and (_KP_RE.search(seg) or _AV_RE.search(seg)):
                continue
            segs.append(seg)
        if segs:
            out.append("; ".join(segs))
    return out


# Chat questions that target a paid technique. If the user's tier lacks the feature,
# we refuse BEFORE calling the model, so it can't be coaxed into fabricating locked
# analysis (e.g. a Basic user asking for their Navamsa D9 sign).
_TOPIC_FEATURE = [
    ("divisional", re.compile(r"navamsa|dasamsa|drekkana|saptamsa|dwadasamsa|trimsamsa|shashtiamsa|"
                              r"\bvarga\b|divisional\s+chart|\bD-?\d{1,2}\b", re.IGNORECASE)),
    ("tables_full", re.compile(r"\bKP\b|sub-?lord|cuspal|ashtakavarga|\bbindus?\b|\bSAV\b|\bBAV\b", re.IGNORECASE)),
    ("varshphal", re.compile(r"varsh?phal|varshaphal|annual\s+(chart|forecast)|solar\s+return|muntha", re.IGNORECASE)),
]
_TOPIC_LABEL = {
    "divisional": "divisional charts (Navamsa D9, Dasamsa D10, and other vargas)",
    "tables_full": "the detailed KP and Ashtakavarga tables",
    "varshphal": "the annual Varshphal forecast",
}


def locked_topic(message: str, features) -> str | None:
    """Return the locked feature a chat question targets (else None)."""
    feats = set(features or ())
    for feat, rx in _TOPIC_FEATURE:
        if feat not in feats and rx.search(message or ""):
            return feat
    return None


def filter_findings(findings, section_keys, features=None):
    """Return only the findings whose category is unlocked by `section_keys`, AND
    strip locked-capability evidence (Navamsa/Dasamsa/KP/Ashtakavarga) when
    `features` is given.

    This is the anti-leak gate for BOTH the reading response (so the network
    payload never contains locked-tier evidence) and the chat context (so the LLM
    physically cannot reveal a tier the user hasn't paid for, even if asked to
    'tell me everything'). Interpretation a tier hasn't unlocked never leaves the
    server."""
    cats = section_categories(section_keys)
    kept = [f for f in findings if getattr(f, "category", None) in cats]
    if features is None:
        return kept
    out = []
    for f in kept:
        ev = _strip_evidence(getattr(f, "evidence", None), features)
        out.append(f.model_copy(update={"evidence": ev}) if hasattr(f, "model_copy") else f)
    return out
