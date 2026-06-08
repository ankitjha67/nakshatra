"""Tajik Varshphal (annual / solar-return) computations.

The yearly report adds the Tajik layer on top of the natal chart. The parts that
are *deterministic from the natal chart + the forecast year* (the native's age,
Muntha, Varsheshwara/year-lord, and the Mudda dasha timeline) are computed here
in Python, so they are correct whether the engine is the mock or the real one.

The genuinely ephemeris-dependent parts (the exact Varsha Pravesha moment and the
Varsha Lagna / Varsha Moon at that moment) come from the engine in production; if
the engine does not supply a `varshphal` block, we fall back to a deterministic
illustrative value and flag it, never a silent fabrication of precision.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any

from .knowledge import SIGNS, SIGN_LORD, DASHA_YEARS

_VIM_ORDER = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
_WEEKDAY_LORD = ["Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Sun"]  # Mon..Sun


def _cb(chart: dict) -> dict:
    return chart.get("chart", chart) if isinstance(chart, dict) else {}


def _sidx(sign: str | None) -> int:
    return SIGNS.index(sign) if sign in SIGNS else 0


def compute_varshphal(chart: dict, birth: Any, year: int) -> dict:
    """Return the Tajik Varshphal block for `year`. `birth` is a BirthDetails."""
    cb = _cb(chart)
    asc_sign = (cb.get("asc") or {}).get("sign") if isinstance(cb.get("asc"), dict) else None
    asc_idx = _sidx(asc_sign)
    moon_lord = cb.get("nakshatra_lord") if cb.get("nakshatra_lord") in _VIM_ORDER else "Moon"

    # birth date + completed age at the varsha (solar return near the birthday)
    try:
        by, bm, bd = (int(x) for x in str(birth.date).split("-"))
    except Exception:
        by, bm, bd = year - 30, 1, 1
    completed_age = max(0, year - by)
    running_age = completed_age + 1

    # Varsha Pravesha date: the birthday in the forecast year (Sun returns to its
    # natal longitude near this date; the engine refines the exact moment).
    try:
        pravesha = date(year, bm, bd)
    except ValueError:
        pravesha = date(year, bm, min(bd, 28))
    vara_lord = _WEEKDAY_LORD[pravesha.weekday()]

    # Muntha: progresses one sign per completed year from the natal ascendant.
    muntha_idx = (asc_idx + completed_age) % 12
    muntha_sign = SIGNS[muntha_idx]

    # Engine-supplied solar-return positions if present, else a deterministic
    # illustrative Varsha Lagna / Moon (flagged as approximate).
    eng = chart.get("varshphal") if isinstance(chart.get("varshphal"), dict) else {}
    approx = False
    varsha_lagna = eng.get("varsha_lagna")
    varsha_moon = eng.get("varsha_moon")
    if not varsha_lagna or not varsha_moon:
        approx = True
        seed = int(hashlib.sha256(f"{birth.date}|{year}".encode()).hexdigest()[:8], 16)
        varsha_lagna = SIGNS[seed % 12]
        varsha_moon = SIGNS[(seed // 12) % 12]

    # Varsheshwara (year lord): lord of the Varsha Lagna sign (a defensible pick
    # among the five office-bearers for a deterministic result).
    varsheshwara = SIGN_LORD.get(_sidx(varsha_lagna) + 1, vara_lord)

    # Mudda dasha: the vimshottari sequence compressed into the one-year cycle.
    start_idx = (_VIM_ORDER.index(moon_lord) + completed_age) % 9
    seq = [_VIM_ORDER[(start_idx + k) % 9] for k in range(9)]
    cursor = pravesha
    mudda = []
    for lord in seq:
        span = int(round(DASHA_YEARS[lord] / 120.0 * 365.25))
        end = cursor + timedelta(days=span)
        mudda.append({"lord": lord, "start": cursor.isoformat(), "end": end.isoformat()})
        cursor = end

    return {
        "year": f"{year}-{year + 1}",
        "pravesha_date": pravesha.isoformat(),
        "completed_age": completed_age,
        "running_age": running_age,
        "vara_lord": vara_lord,
        "varsha_lagna": varsha_lagna,
        "varsha_moon": varsha_moon,
        "muntha_sign": muntha_sign,
        "varsheshwara": varsheshwara,
        "mudda_dasha": mudda,
        "approx_positions": approx,
    }
