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

from typing import Any

# blocks unlocked only by the "tables_full" capability (Pro+)
_FULL_TABLE_BLOCKS = (
    "jaimini_karakas", "kp_significators", "numerology",
    "yogi_avayogi", "bhrigu_bindu", "double_transit", "sade_sati",
)


def filter_chart_for_features(chart: dict, features: set[str] | frozenset[str]) -> dict[str, Any]:
    """Return a shallow copy of the engine chart with blocks the tier lacks removed."""
    if not isinstance(chart, dict):
        return chart
    out = dict(chart)

    if "divisional" not in features:
        out.pop("vargas", None)                       # D9/D10/D24 selector goes away

    if "tables_full" not in features:
        for k in _FULL_TABLE_BLOCKS:
            out.pop(k, None)
        ds = out.get("dasha_systems")
        if isinstance(ds, dict):                      # keep only Vimshottari for tables_basic
            out["dasha_systems"] = {k: v for k, v in ds.items() if k == "vimshottari"}

    if "tables_basic" not in features:
        out.pop("dasha_systems", None)                # free: no dasha table at all

    return out
