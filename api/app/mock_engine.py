"""A deterministic placeholder engine that imitates the Maha-Jyotish v7 contract.

It emits a plausible, internally-consistent Vedic chart in the SAME nested JSON
shape your real engine produces, so the whole pipeline (engine -> rules -> LLM)
runs over the exact structure it will see in production — before the real engine
is connected. It is seeded by the birth-detail hash, so the same input always
yields the same chart (which is what makes caching meaningful). It is NOT
astronomically accurate — it is a faithful *shape* stand-in, not an ephemeris.

Shape emitted (subset of Maha-Jyotish v7 that the rules layer consumes):

    {
      "engine": "mock",
      "chart": {
        "asc": {"sign": "Scorpio", "degree": 12.3, "nakshatra": "Anuradha"},
        "planets": {
          "Sun": {"sign": "Cancer", "degree": 18.4, "nakshatra": "Pushya",
                  "pada": 2,
                  "status": {"dignity": "Debilitated", "retrograde": false,
                             "combust": false, "gandanta": false}},
          ...
        },
        "moon_nakshatra": "Rohini",
        "nakshatra_lord": "Moon"
      },
      "yogas": {"detected": [{"name": "...", "planets": [...], "description": "..."}]},
      "conjunctions": [{"planet_1":"Jupiter","planet_2":"Venus","separation":1.2,"strength":"Close"}],
      "jaimini_karakas": {"Atmakaraka": {"planet": "Sun", "sign": "Cancer"}},
      "sade_sati": {"active": false, "phase": ""},
      "danger_zones": {"gandanta_planets": [{"planet": "Sun"}]},
      "dasha_systems": {"vimshottari": {"current": {
          "mahadasha": "Jupiter", "md_start": "2017-...", "md_end": "2033-...",
          "antardasha": "Venus", "ad_start": "...", "ad_end": "..."}}}
    }
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta
from typing import Any

from .knowledge import (
    GRAHAS, SIGNS, EXALT_SIGN, OWN_SIGNS, NAKSHATRAS,
    NAKSHATRA_LORD, DASHA_YEARS, opposite_sign,
)

_NAK_ARC = 40.0 / 3.0     # 13.3333° per nakshatra
_PADA_ARC = 10.0 / 3.0    # 3.3333° per pada
_WATER = {4, 8, 12}       # Cancer, Scorpio, Pisces
_FIRE = {1, 5, 9}         # Aries, Leo, Sagittarius


def _dignity(planet: str, sign_idx: int) -> str:
    """Return dignity using the real engine's capitalisation."""
    if planet in ("Rahu", "Ketu"):
        return "Normal"
    if EXALT_SIGN.get(planet) == sign_idx:
        return "Exalted"
    if EXALT_SIGN.get(planet) and opposite_sign(EXALT_SIGN[planet]) == sign_idx:
        return "Debilitated"
    if sign_idx in OWN_SIGNS.get(planet, []):
        return "Own Sign"
    return "Normal"


def _ang_sep(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _is_gandanta(sign_idx: int, deg: float) -> bool:
    if sign_idx in _WATER and deg >= 26.6667:
        return True
    if sign_idx in _FIRE and deg <= 3.3333:
        return True
    return False


def _nak_at(longitude: float) -> tuple[str, str, int]:
    """(nakshatra name, vimshottari lord, pada 1-4) for an absolute longitude."""
    nidx = int(longitude // _NAK_ARC) % 27 + 1
    within = longitude % _NAK_ARC
    pada = int(within // _PADA_ARC) + 1
    pada = max(1, min(4, pada))
    return NAKSHATRAS[nidx - 1], NAKSHATRA_LORD[nidx], pada


def _kendra(h1: int, h2: int) -> bool:
    return ((h1 - h2) % 12) in (0, 3, 6, 9)


def compute_mock_chart(birth: dict) -> dict[str, Any]:
    canonical = "|".join(str(birth.get(k, "")) for k in
                         ("date", "time", "tz", "lat", "lon", "ayanamsa", "house_system"))
    seed = int(hashlib.sha256(canonical.encode()).hexdigest(), 16) % (2 ** 32)
    rng = random.Random(seed)

    asc_idx = rng.randint(1, 12)
    asc_deg = round(rng.uniform(0, 29.99), 2)
    asc_lon = (asc_idx - 1) * 30 + asc_deg

    # --- place the grahas ---
    sign_idx: dict[str, int] = {}
    deg: dict[str, float] = {}
    lon: dict[str, float] = {}
    for g in GRAHAS:
        s = rng.randint(1, 12)
        d = round(rng.uniform(0, 29.99), 2)
        sign_idx[g] = s
        deg[g] = d
        lon[g] = (s - 1) * 30 + d

    sun_lon = lon["Sun"]
    planets: dict[str, dict] = {}
    for g in GRAHAS:
        s, d = sign_idx[g], deg[g]
        nak, _nl, pada = _nak_at(lon[g])
        retro = True if g in ("Rahu", "Ketu") else rng.random() < 0.18
        combust = False
        if g not in ("Sun", "Rahu", "Ketu"):
            lim = 12.0 if g == "Moon" else 8.0
            combust = _ang_sep(lon[g], sun_lon) < lim
        planets[g] = {
            "sign": SIGNS[s - 1],
            "degree": d,
            "nakshatra": nak,
            "pada": pada,
            "status": {
                "dignity": _dignity(g, s),
                "retrograde": retro,
                "combust": combust,
                "gandanta": _is_gandanta(s, d),
            },
        }

    moon_nak, moon_nak_lord, _mp = _nak_at(lon["Moon"])
    asc_nak, _al, _ap = _nak_at(asc_lon)

    house_of = {g: ((sign_idx[g] - asc_idx) % 12) + 1 for g in GRAHAS}

    # --- classical yogas, only if actually present (v7 "detected" shape) ---
    detected: list[dict] = []
    if _kendra(house_of["Moon"], house_of["Jupiter"]):
        detected.append({"name": "Gajakesari Yoga", "planets": ["Moon", "Jupiter"],
                         "description": "wisdom, reputation and lasting well-being"})
    if sign_idx["Sun"] == sign_idx["Mercury"]:
        detected.append({"name": "Budhaditya Yoga", "planets": ["Sun", "Mercury"],
                         "description": "sharp intelligence and articulate expression"})
    if sign_idx["Moon"] == sign_idx["Mars"]:
        detected.append({"name": "Chandra-Mangala Yoga", "planets": ["Moon", "Mars"],
                         "description": "drive, resourcefulness and material capability"})

    # --- conjunctions (same-sign pairs, with separation + strength band) ---
    conjunctions: list[dict] = []
    for i, a in enumerate(GRAHAS):
        for b in GRAHAS[i + 1:]:
            if sign_idx[a] == sign_idx[b]:
                sep = round(abs(deg[a] - deg[b]), 2)
                strength = "Very Close" if sep < 1 else "Close" if sep < 5 else "Wide"
                conjunctions.append({"planet_1": a, "planet_2": b,
                                     "separation": sep, "strength": strength})
    conjunctions.sort(key=lambda c: c["separation"])

    # --- Jaimini Atmakaraka: highest degree among the 7 tropical grahas ---
    seven = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
    ak = max(seven, key=lambda g: deg[g])

    # --- Sade Sati: crude deterministic flag (mock only) ---
    ss_active = rng.random() < 0.30
    ss_phase = rng.choice(["Rising", "Peak", "Setting"]) if ss_active else ""

    # --- gandanta danger zone list ---
    gz = [{"planet": g} for g in GRAHAS if planets[g]["status"]["gandanta"]]

    # --- vimshottari: maha + antar windows from the Moon's nakshatra lord ---
    order = list(DASHA_YEARS.keys())
    i0 = order.index(moon_nak_lord)
    seq = [order[(i0 + k) % 9] for k in range(9)]

    bdate = date.fromisoformat(birth["date"])
    elapsed0 = rng.uniform(0, DASHA_YEARS[moon_nak_lord])
    cursor = bdate - timedelta(days=int(elapsed0 * 365.25))
    maha_periods = []
    for lord in seq:
        end = cursor + timedelta(days=int(DASHA_YEARS[lord] * 365.25))
        maha_periods.append((lord, cursor, end))
        cursor = end

    today = date.today()
    maha = next((p for p in maha_periods if p[1] <= today < p[2]), maha_periods[0])
    maha_lord, m_start, m_end = maha

    # antardashas inside the running mahadasha: fraction = antar_years / 120
    m_span = (m_end - m_start).days or 1
    m_idx = order.index(maha_lord)
    antar_seq = [order[(m_idx + k) % 9] for k in range(9)]
    ad_cursor = m_start
    antar_lord, ad_start, ad_end = antar_seq[0], m_start, m_end
    for lord in antar_seq:
        frac = DASHA_YEARS[lord] / 120.0
        end = ad_cursor + timedelta(days=int(m_span * frac))
        if ad_cursor <= today < end:
            antar_lord, ad_start, ad_end = lord, ad_cursor, end
            break
        ad_cursor = end

    return {
        "engine": "mock",
        "input": {k: birth.get(k) for k in ("name", "date", "time", "tz", "lat", "lon")},
        "chart": {
            "asc": {"sign": SIGNS[asc_idx - 1], "degree": asc_deg, "nakshatra": asc_nak},
            "planets": planets,
            "moon_nakshatra": moon_nak,
            "nakshatra_lord": moon_nak_lord,
        },
        "yogas": {"detected": detected},
        "conjunctions": conjunctions,
        "jaimini_karakas": {"Atmakaraka": {"planet": ak, "sign": SIGNS[sign_idx[ak] - 1]}},
        "sade_sati": {"active": ss_active, "phase": ss_phase},
        "danger_zones": {"gandanta_planets": gz},
        "dasha_systems": {"vimshottari": {"current": {
            "mahadasha": maha_lord,
            "md_start": m_start.isoformat(),
            "md_end": m_end.isoformat(),
            "antardasha": antar_lord,
            "ad_start": ad_start.isoformat(),
            "ad_end": ad_end.isoformat(),
        }}},
        "_engine": "mock",
    }
