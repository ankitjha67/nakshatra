"""Anchor Verification Block, the Maha-Jyotish "verify before you read" protocol.

Before the full Maha-Kundali is rendered, the user is shown the chart's *anchor*:
the Western Tropical vs Vedic Sidereal Ascendant & Moon, the Nakshatra lock, the
timezone/ayanamsa/house-system used, and any preliminary danger-zone flags. The
user confirms it against an external panchang (DrikPanchang / AstroSage) before
the reading proceeds, or supplies a "Golden Truth" correction.

This module is pure: it reads the engine chart JSON (defensively, same shape as
rules.py) and derives the anchor. No interpretation, no LLM, just the facts the
user must verify. Tropical positions are derived from the sidereal ones by adding
the Lahiri ayanamsa, so they line up with the same engine output.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .knowledge import SIGNS, NAKSHATRAS, NAKSHATRA_LORD

_NAK_SPAN = 360.0 / 27.0  # 13°20'
_PADA_SPAN = _NAK_SPAN / 4.0  # 3°20'


# --------------------------------------------------------------------------- #
# defensive readers (mirror rules.py; tolerate mock "degree" and engine "deg")
# --------------------------------------------------------------------------- #
def _cb(chart: dict) -> dict:
    return chart.get("chart", chart) if isinstance(chart, dict) else {}


def _deg_in_sign(node: Any) -> float:
    if isinstance(node, dict):
        for k in ("deg", "degree", "degree_in_sign"):
            v = node.get(k)
            if isinstance(v, (int, float)):
                return float(v) % 30.0
    return 15.0  # neutral fallback so a sign-only engine still anchors


def _abs_lon(sign: str | None, node: Any) -> float | None:
    if sign in SIGNS:
        return SIGNS.index(sign) * 30.0 + _deg_in_sign(node)
    return None


def _ayanamsa_deg(year: int) -> float:
    # Lahiri (Chitrapaksha), good to ~1 arcmin across the modern era.
    return 22.46 + 0.013888 * (year - 1900)


def _fmt(abs_lon: float) -> dict:
    sign = SIGNS[int(abs_lon // 30) % 12]
    d_in = abs_lon % 30.0
    d = int(d_in)
    m = int(round((d_in - d) * 60))
    if m == 60:
        d, m = d + 1, 0
    return {"sign": sign, "deg": round(d_in, 2), "fmt": f"{sign} {d}°{m:02d}′"}


def _nakshatra_at(abs_lon: float) -> dict:
    idx = int(abs_lon // _NAK_SPAN) % 27
    pada = int((abs_lon % _NAK_SPAN) // _PADA_SPAN) + 1
    return {"name": NAKSHATRAS[idx], "pada": pada, "lord": NAKSHATRA_LORD[idx + 1]}


# --------------------------------------------------------------------------- #
# anchor derivation
# --------------------------------------------------------------------------- #
def derive_anchor(chart: dict, birth: Any) -> dict:
    """Return the anchor block. `birth` is a BirthDetails (read for tz/place/year)."""
    cb = _cb(chart)
    planets = cb.get("planets") or cb.get("grahas") or {}
    if not isinstance(planets, dict):
        planets = {}

    try:
        yr = int(str(getattr(birth, "date", "")).split("-")[0])
    except Exception:
        yr = date.today().year
    aya = _ayanamsa_deg(yr)

    # --- ascendant: sidereal from the engine, tropical = sidereal + ayanamsa ---
    asc = cb.get("asc") or cb.get("ascendant") or cb.get("lagna") or {}
    asc_sign = asc.get("sign") if isinstance(asc, dict) else (asc if isinstance(asc, str) else None)
    asc_sid = _abs_lon(asc_sign, asc)

    moon = planets.get("Moon") or planets.get("moon") or {}
    moon_sign = moon.get("sign") if isinstance(moon, dict) else None
    moon_sid = _abs_lon(moon_sign, moon)

    sidereal = {
        "asc": _fmt(asc_sid) if asc_sid is not None else None,
        "moon": _fmt(moon_sid) if moon_sid is not None else None,
    }
    tropical = {
        "asc": _fmt((asc_sid + aya) % 360) if asc_sid is not None else None,
        "moon": _fmt((moon_sid + aya) % 360) if moon_sid is not None else None,
    }

    # --- nakshatra lock (prefer engine's stated name; pada/lord computed) ---
    nak = None
    if moon_sid is not None:
        nak = _nakshatra_at(moon_sid)
        engine_nak = cb.get("moon_nakshatra")
        if engine_nak in NAKSHATRAS:
            nak["name"] = engine_nak
            nak["lord"] = NAKSHATRA_LORD[NAKSHATRAS.index(engine_nak) + 1]
        if isinstance(cb.get("moon_pada"), int):
            nak["pada"] = cb["moon_pada"]

    # --- preliminary danger-zone flags ---
    flags: list[dict] = []
    combust: list[str] = []
    mrityu: list[str] = []
    gandanta: list[str] = []
    for name, p in planets.items():
        if not isinstance(p, dict):
            continue
        st = p.get("status") or {}
        bits: list[str] = []
        if st.get("retrograde") and name not in ("Rahu", "Ketu"):
            bits.append("Retrograde")
        dig = str(st.get("dignity") or p.get("dignity") or "")
        if dig.lower().startswith("debil"):
            bits.append("Debilitated")
        if st.get("gandanta"):
            bits.append("Gandanta")
            gandanta.append(name)
        if st.get("combust"):
            bits.append("Combust")
            combust.append(name)
        if st.get("mrityu_bhaga"):
            bits.append("Mrityu Bhaga")
            mrityu.append(name)
        if bits:
            flags.append({"factor": name, "status": " + ".join(bits)})

    checks = [
        {"label": "Combustion", "value": ", ".join(combust) or "None detected"},
        {"label": "Gandanta", "value": ", ".join(gandanta) or "None detected"},
        {"label": "Mrityu Bhaga", "value": ", ".join(mrityu) or "None detected"},
    ]

    return {
        "name": getattr(birth, "name", None) or "Friend",
        "input": {
            "date": getattr(birth, "date", None),
            "time": getattr(birth, "time", None),
            "place": getattr(birth, "place", None),
            "lat": getattr(birth, "lat", None),
            "lon": getattr(birth, "lon", None),
        },
        "timezone": {
            "offset": getattr(birth, "tz", None),
            "note": "DST is already incorporated into the UTC offset shown.",
        },
        "ayanamsa": (getattr(birth, "ayanamsa", "lahiri") or "lahiri").title(),
        "ayanamsa_deg": round(aya, 3),
        "house_system": "Placidus-KP" if "kp" in str(getattr(birth, "house_system", "")).lower()
                         else (getattr(birth, "house_system", "whole_sign") or "whole_sign").replace("_", " ").title(),
        "sidereal": sidereal,
        "tropical": tropical,
        "nakshatra": nak,
        "danger_flags": flags,
        "checks": checks,
    }
