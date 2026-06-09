"""Kundali Matching, Ashtakoot Guna Milan (36 points) + Manglik compatibility.

Deterministic, from each person's Moon nakshatra index (0-26) and Moon rashi index
(0-11). This is the classical 8-koota system used across the segment. Yoni and Vashya
use a pragmatic (slightly simplified) compatibility table; Varna, Tara, Graha Maitri,
Gana, Bhakoot and Nadi follow the standard rules. The numbers are computed here
(anti-slop); the LLM only phrases the result.
"""
from __future__ import annotations

from .knowledge import SIGN_LORD

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu",
    "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni", "Hasta",
    "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha",
    "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha", "Purva Bhadrapada",
    "Uttara Bhadrapada", "Revati",
]
# per-nakshatra attributes (index 0..26)
_GANA = [0, 1, 2, 1, 0, 1, 0, 0, 2, 2, 1, 1, 0, 2, 0, 2, 0, 2, 2, 1, 1, 0, 2, 2, 1, 1, 0]  # 0 Deva 1 Manushya 2 Rakshasa
_NADI = [0, 1, 2, 2, 1, 0, 0, 1, 2, 2, 1, 0, 0, 1, 2, 2, 1, 0, 0, 1, 2, 2, 1, 0, 0, 1, 2]  # 0 Aadi 1 Madhya 2 Antya
_YONI = ["horse", "elephant", "sheep", "serpent", "serpent", "dog", "cat", "sheep", "cat",
         "rat", "rat", "cow", "buffalo", "tiger", "buffalo", "tiger", "hare", "hare", "dog",
         "monkey", "mongoose", "monkey", "lion", "horse", "lion", "cow", "elephant"]
_YONI_ENEMY = {frozenset(p) for p in
               [("cow", "tiger"), ("horse", "buffalo"), ("elephant", "lion"), ("sheep", "monkey"),
                ("serpent", "mongoose"), ("dog", "hare"), ("cat", "rat")]}
# per-rashi (0 Aries .. 11 Pisces)
_VARNA = [2, 1, 0, 3, 2, 1, 0, 3, 2, 1, 0, 3]              # 3 Brahmin 2 Kshatriya 1 Vaishya 0 Shudra
_VASHYA = [0, 0, 1, 2, 3, 1, 1, 4, 1, 2, 1, 2]            # 0 quad 1 human 2 water 3 wild 4 insect
_FRIEND = {  # natural planetary friendship (friends, enemies); rest neutral
    "Sun": ({"Moon", "Mars", "Jupiter"}, {"Venus", "Saturn"}),
    "Moon": ({"Sun", "Mercury"}, set()),
    "Mars": ({"Sun", "Moon", "Jupiter"}, {"Mercury"}),
    "Mercury": ({"Sun", "Venus"}, {"Moon"}),
    "Jupiter": ({"Sun", "Moon", "Mars"}, {"Mercury", "Venus"}),
    "Venus": ({"Mercury", "Saturn"}, {"Sun", "Moon"}),
    "Saturn": ({"Mercury", "Venus"}, {"Sun", "Moon", "Mars"}),
}
_MANGAL_HOUSES = {1, 2, 4, 7, 8, 12}


def _rel(a: str, b: str) -> str:
    fr, en = _FRIEND.get(a, (set(), set()))
    return "F" if b in fr else ("E" if b in en else "N")


def _varna(rb: int, rg: int) -> int:
    return 1 if _VARNA[rb] >= _VARNA[rg] else 0


def _vashya(rb: int, rg: int) -> float:
    return 2.0 if _VASHYA[rb] == _VASHYA[rg] else 1.0


def _tara(nb: int, ng: int) -> float:
    def ok(frm, to):
        t = ((to - frm) % 27 + 1) % 9
        return (t or 9) not in (3, 5, 7)
    return (1.5 if ok(ng, nb) else 0) + (1.5 if ok(nb, ng) else 0)


def _yoni(nb: int, ng: int) -> int:
    a, b = _YONI[nb], _YONI[ng]
    if a == b:
        return 4
    if frozenset((a, b)) in _YONI_ENEMY:
        return 0
    return 2


def _maitri(rb: int, rg: int) -> float:
    lb, lg = SIGN_LORD[rb + 1], SIGN_LORD[rg + 1]
    if lb == lg:
        return 5.0
    pair = {_rel(lb, lg), _rel(lg, lb)}
    if pair == {"F"}:
        return 5.0
    if pair == {"F", "N"}:
        return 4.0
    if pair == {"N"}:
        return 3.0
    if pair == {"F", "E"}:
        return 1.0
    if pair == {"N", "E"}:
        return 0.5
    return 0.0  # both enemy


def _gana(nb: int, ng: int) -> int:
    gb, gg = _GANA[nb], _GANA[ng]
    if gb == gg:
        return 6
    s = {gb, gg}
    if s == {0, 1}:      # Deva + Manushya
        return 5
    if s == {0, 2}:      # Deva + Rakshasa
        return 1
    return 0             # Manushya + Rakshasa


def _bhakoot(rb: int, rg: int) -> int:
    diff = (rg - rb) % 12
    return 0 if diff in (1, 4, 5, 7, 8, 11) else 7   # 2-12, 5-9, 6-8 dosha


def _nadi(nb: int, ng: int) -> int:
    return 0 if _NADI[nb] == _NADI[ng] else 8


def ashtakoot(nak_boy: int, rashi_boy: int, nak_girl: int, rashi_girl: int) -> dict:
    """8-koota Guna Milan. `boy`/`girl` are conventional labels (groom/bride); the
    asymmetric kutas (Varna, Gana, Bhakoot) use that convention."""
    kutas = [
        ("Varna", _varna(rashi_boy, rashi_girl), 1, "spiritual/ego compatibility"),
        ("Vashya", _vashya(rashi_boy, rashi_girl), 2, "mutual attraction and control"),
        ("Tara", _tara(nak_boy, nak_girl), 3, "health and well-being of the union"),
        ("Yoni", _yoni(nak_boy, nak_girl), 4, "physical and instinctive compatibility"),
        ("Graha Maitri", _maitri(rashi_boy, rashi_girl), 5, "mental and intellectual bond"),
        ("Gana", _gana(nak_boy, nak_girl), 6, "temperament and nature"),
        ("Bhakoot", _bhakoot(rashi_boy, rashi_girl), 7, "love, family welfare and prosperity"),
        ("Nadi", _nadi(nak_boy, nak_girl), 8, "health and progeny (heaviest weight)"),
    ]
    total = round(sum(k[1] for k in kutas), 1)
    verdict = ("Excellent" if total >= 28 else "Good" if total >= 24 else
               "Acceptable" if total >= 18 else "Low")
    return {
        "kutas": [{"name": n, "score": s, "max": m, "of": o} for n, s, m, o in kutas],
        "total": total, "max": 36, "verdict": verdict,
        "nadi_dosha": _nadi(nak_boy, nak_girl) == 0,
        "bhakoot_dosha": _bhakoot(rashi_boy, rashi_girl) == 0,
    }


def is_manglik(mars_house_from_lagna: int | None, mars_house_from_moon: int | None) -> bool:
    return (mars_house_from_lagna in _MANGAL_HOUSES) or (mars_house_from_moon in _MANGAL_HOUSES)
