# engine_app.py — adapter between the API and your Maha-Jyotish v7 monolith.
#
# Place your engine file (maha_jyotish_cloud_engine.py) next to this file at the
# project root so the import below resolves. Then set in .env:
#     ENGINE_MODULE=engine_app
#     ENGINE_CALLABLE=compute_chart
#     ENGINE_VERSION=maha-jyotish-7.0
from __future__ import annotations

import re
from typing import Any


# --------------------------------------------------------------------------- #
# pysweph / pyswisseph compatibility shim
# --------------------------------------------------------------------------- #
# Your engine was written for the original `pyswisseph`. On Python 3.13+ the only
# installable build is the community fork `pysweph`, which has TWO documented
# breaking changes we must neutralise so the engine runs unchanged:
#
#   * v2.10.3.3 — calc(), calc_ut(), calc_pctr(), deltat_ex() return an EXTRA
#                 trailing error-string. Old code does `xx, ret = swe.calc_ut(...)`
#                 (2 values); the fork returns 3 -> "too many values to unpack".
#   * v2.10.3.4 — the houses() family returns cusps as a 13- (or 37-) item tuple
#                 with index 0 empty, instead of the classic 12 (or 36).
#
# We monkeypatch the `swisseph` module object once, BEFORE the engine uses it,
# to restore the original return shapes. On the original pyswisseph (or if the
# module is absent) this is a harmless no-op.
def _patch_swisseph() -> None:
    try:
        import swisseph as swe
    except Exception:
        return  # not installed — the engine will raise its own clear error
    if getattr(swe, "_jc_compat_patched", False):
        return

    def _calc_factory(orig):
        def wrapper(*a, **k):
            res = orig(*a, **k)
            # fork: (xx, retflag, serr) -> original: (xx, retflag)
            if isinstance(res, tuple) and len(res) > 2:
                return res[0], res[1]
            return res
        return wrapper

    for name in ("calc", "calc_ut", "calc_pctr"):
        orig = getattr(swe, name, None)
        if callable(orig):
            setattr(swe, name, _calc_factory(orig))

    _dt = getattr(swe, "deltat_ex", None)
    if callable(_dt):
        def _deltat_wrapper(*a, _orig=_dt, **k):
            res = _orig(*a, **k)
            # fork: (deltat, serr) -> original: deltat
            if isinstance(res, tuple) and res:
                return res[0]
            return res
        setattr(swe, "deltat_ex", _deltat_wrapper)

    def _houses_factory(orig):
        def wrapper(*a, **k):
            res = orig(*a, **k)
            # fork: (cusps[13 or 37], ascmc, ...) with cusps[0] empty
            #   ->  original: (cusps[12 or 36], ascmc, ...)
            if isinstance(res, tuple) and res:
                cusps = res[0]
                if isinstance(cusps, (tuple, list)) and len(cusps) in (13, 37):
                    return (tuple(cusps)[1:],) + tuple(res[1:])
            return res
        return wrapper

    for name in ("houses", "houses_ex"):
        orig = getattr(swe, name, None)
        if callable(orig):
            setattr(swe, name, _houses_factory(orig))

    swe._jc_compat_patched = True


_patch_swisseph()

# Your monolith's clean JSON entry point already returns a dict.
from maha_jyotish_cloud_engine import calculate_chart_json  # noqa: E402

# Reported to the API and folded into the cache key.
__version__ = "maha-jyotish-7.0"


def _tz_to_float(tz: Any) -> float:
    """Accept '+05:30' | '5.5' | 5.5 -> hours as float (e.g. 5.5)."""
    if isinstance(tz, (int, float)):
        return float(tz)
    if not tz:
        return 0.0
    s = str(tz).strip().upper().replace("UTC", "").replace("GMT", "").strip()
    m = re.match(r"([+-]?)(\d{1,2}):?(\d{2})?$", s)
    if not m:
        try:
            return float(s)
        except ValueError:
            return 0.0
    sign = -1 if m.group(1) == "-" else 1
    return sign * (int(m.group(2)) + int(m.group(3) or 0) / 60.0)


def compute_chart(birth: dict) -> dict:
    """Called by app/engine.py. `birth` holds the BirthDetails fields.

    The engine's date parser accepts 'YYYY-MM-DD', and tz is converted to a
    numeric offset. Everything else maps straight across.
    """
    return calculate_chart_json(
        name=birth.get("name") or "User",
        dob=birth["date"],                 # e.g. "1990-08-15"
        tob=birth["time"],                 # e.g. "14:30"
        lat=float(birth["lat"]),
        lon=float(birth["lon"]),
        tz_offset=_tz_to_float(birth.get("tz", 0.0)),
    )
