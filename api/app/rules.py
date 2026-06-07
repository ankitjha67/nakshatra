"""Rules layer — the anti-slop engine, tuned for the Maha-Jyotish v7 output.

It reads the engine's JSON and emits `Finding`s: factual, jyotish-correct
statements with explicit evidence. All interpretation lives here; the LLM
downstream only re-phrases these and must cite them.

Maha-Jyotish v7 shape this reads:
  chart["chart"]["asc"]              -> {"sign": "Scorpio", "nakshatra": ...}
  chart["chart"]["planets"][NAME]    -> {"sign": "Cancer", "nakshatra": ...,
                                          "status": {"dignity","retrograde","combust","gandanta"}}
  chart["chart"]["moon_nakshatra"], ["nakshatra_lord"]
  chart["dasha_systems"]["vimshottari"]["current"]  -> mahadasha/antardasha + windows
  chart["yogas"]["detected"], chart["conjunctions"], chart["jaimini_karakas"],
  chart["sade_sati"], chart["danger_zones"]

Houses are computed whole-sign (rashi) from the ascendant — the standard frame
for narrative Vedic interpretation. (Switch to chart["bhava_chalit"] if you
prefer Placidus bhava.) The mundane/financial blocks (CSP, Nava Nayaka, Sapta
Nadi, etc.) are intentionally NOT used for a personal reading — they describe
the world/markets, not the individual, and would be noise here.
"""
from __future__ import annotations

from typing import Any

from .knowledge import SIGNS, SIGN_LORD, KARAKA, HOUSE_MEANING, GRAHA_CATEGORY, EXALT_SIGN, OWN_SIGNS
from .models import Finding


# --------------------------------------------------------------------------- #
# defensive readers for the v7 shape
# --------------------------------------------------------------------------- #
def _d(x: Any) -> dict:
    """Coerce to dict — guards against an engine emitting a list/None where we expect a map."""
    return x if isinstance(x, dict) else {}


def _l(x: Any) -> list:
    """Coerce to list — guards against an engine emitting a dict/None where we expect a sequence."""
    return x if isinstance(x, list) else []


def _cb(chart: dict) -> dict:
    return _d(chart).get("chart", chart)  # planets/asc live under "chart"


def _planets(chart: dict) -> list[dict]:
    pl = _cb(chart).get("planets") or _cb(chart).get("grahas") or {}
    out: list[dict] = []
    if isinstance(pl, dict):
        for name, p in pl.items():
            st = (p.get("status") or {}) if isinstance(p, dict) else {}
            out.append({
                "name": name,
                "sign": p.get("sign"),
                "nakshatra": p.get("nakshatra"),
                "dignity": str(st.get("dignity") or p.get("dignity") or "Normal"),
                "retrograde": bool(st.get("retrograde", p.get("retrograde", False))),
                "combust": bool(st.get("combust", False)),
                "gandanta": bool(st.get("gandanta", False)),
            })
    elif isinstance(pl, list):
        out = pl
    return out


def _by_name(planets: list[dict]) -> dict[str, dict]:
    return {str(p.get("name")): p for p in planets}


def _asc_sign(chart: dict) -> str | None:
    a = _cb(chart).get("asc") or _cb(chart).get("ascendant") or _cb(chart).get("lagna") or {}
    if isinstance(a, dict):
        return a.get("sign")
    return a if isinstance(a, str) else None


def _dasha_current(chart: dict) -> dict:
    ds = _d(chart.get("dasha_systems"))
    vim = _d(ds.get("vimshottari")) or _d(chart.get("vimshottari"))
    return _d(vim.get("current"))


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _sidx(sign: str | None) -> int | None:
    if sign and sign in SIGNS:
        return SIGNS.index(sign)  # 0-based
    return None


def _lord_of(sign: str | None) -> str | None:
    i = _sidx(sign)
    return SIGN_LORD[i + 1] if i is not None else None


def _house_ws(planet_sign: str | None, asc_sign: str | None) -> int | None:
    ps, a = _sidx(planet_sign), _sidx(asc_sign)
    if ps is None or a is None:
        return None
    return ((ps - a) % 12) + 1


def _ord(n: int | None) -> str:
    if not n:
        return "?"
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def _karaka(p: str) -> str:
    return KARAKA.get(p, "its themes")


def _sign_in_house(asc_sign: str | None, house: int) -> str | None:
    a = _sidx(asc_sign)
    if a is None:
        return None
    return SIGNS[(a + house - 1) % 12]


def _occupants(by: dict[str, dict], asc_sign: str | None, house: int) -> list[str]:
    return [n for n, p in by.items() if _house_ws(p.get("sign"), asc_sign) == house]


def _strength_phrase(dignity: str | None) -> str:
    d = str(dignity or "").lower()
    if d == "exalted":
        return " where it is exalted (very strong)"
    if d == "own sign":
        return " in its own sign (strong)"
    if d == "moolatrikona":
        return " in moolatrikona (strong)"
    if d == "debilitated":
        return " where it is debilitated — a tested placement that matures with conscious effort"
    return ""


# --------------------------------------------------------------------------- #
# rule generators
# --------------------------------------------------------------------------- #
def _lagna(chart, by, asc_sign) -> list[Finding]:
    out: list[Finding] = []
    if not asc_sign:
        return out
    lord = _lord_of(asc_sign)
    out.append(Finding(
        code="LAGNA.SIGN", category="essence", polarity="neutral", weight=8,
        title=f"{asc_sign} ascendant",
        detail=(f"The ascendant is {asc_sign}, ruled by {lord}. This sets the lens of the whole "
                f"chart: the condition and placement of {lord} colours the overall direction of life."),
        evidence=[f"Ascendant: {asc_sign} (lord {lord})"],
    ))
    lp = by.get(lord) if lord else None
    if lp and lp.get("sign"):
        h = _house_ws(lp["sign"], asc_sign)
        dig = lp.get("dignity", "Normal")
        strength = f" and is {dig.lower()} there" if dig and dig.lower() in (
            "exalted", "own sign", "moolatrikona") else ""
        out.append(Finding(
            code="LAGNA.LORD", category="essence", polarity="neutral", weight=9,
            title=f"Chart ruler {lord} in the {_ord(h)} house",
            detail=(f"{lord}, ruler of the {asc_sign} ascendant, sits in the {_ord(h)} house "
                    f"in {lp['sign']}{strength} — so the themes of {HOUSE_MEANING.get(h,'that house')} "
                    f"are central to how this life unfolds."),
            evidence=[f"{lord} (lagna lord) in {lp['sign']}, {_ord(h)} house"],
        ))
    return out


def _dignities(by, asc_sign) -> list[Finding]:
    out: list[Finding] = []
    table = {"exalted": ("supportive", 8), "own sign": ("supportive", 6),
             "moolatrikona": ("supportive", 7), "debilitated": ("challenging", 7)}
    for name, p in by.items():
        dig = str(p.get("dignity", "Normal")).lower()
        if dig not in table:
            continue
        polarity, weight = table[dig]
        h = _house_ws(p.get("sign"), asc_sign)
        where = f", {_ord(h)} house" if h else ""
        if dig == "debilitated":
            detail = (f"{name} is debilitated in {p.get('sign')}{where}. The matters it governs "
                      f"— {_karaka(name)} — are tested earlier and tend to mature later, often "
                      f"becoming a real source of depth once consciously worked with.")
        else:
            detail = (f"{name} is strong ({dig}) in {p.get('sign')}{where}, supporting "
                      f"{_karaka(name)} as a natural strength to lean on.")
        out.append(Finding(
            code=f"DIGNITY.{name.upper()}", category=GRAHA_CATEGORY.get(name, "essence"),
            polarity=polarity, weight=weight,
            title=f"{name} {dig} in {p.get('sign')}",
            detail=detail, evidence=[f"{name} {dig} in {p.get('sign')}{where}"],
        ))
    return out


def _moon_nakshatra(chart, by, asc_sign) -> list[Finding]:
    cb = _cb(chart)
    nak = cb.get("moon_nakshatra")
    lord = cb.get("nakshatra_lord")
    moon = by.get("Moon")
    if not nak or not moon:
        return []
    dig = str(moon.get("dignity", "Normal")).lower()
    strength = f", where it is {dig}" if dig in ("exalted", "own sign", "moolatrikona", "debilitated") else ""
    h = _house_ws(moon.get("sign"), asc_sign)
    return [Finding(
        code="MOON.NAKSHATRA", category="mind", polarity="neutral", weight=7,
        title=f"Moon in {nak}",
        detail=(f"The emotional mind is shaped by the Moon in {nak} (ruled by {lord}), placed in "
                f"{moon.get('sign')}{strength} in the {_ord(h)} house. This nakshatra and sign set the "
                f"baseline temperament and what brings a felt sense of security."),
        evidence=[f"Moon in {nak} ({moon.get('sign')}, {_ord(h)} house); nakshatra lord {lord}"],
    )]


def _dasha(chart, by) -> list[Finding]:
    cur = _dasha_current(chart)
    ml = cur.get("mahadasha")
    al = cur.get("antardasha")
    if not ml:
        return []
    win = ""
    if cur.get("md_start") and cur.get("md_end"):
        win = f" (running ~{cur['md_start']} to {cur['md_end']})"
    detail = (f"The current major period (Mahadasha) is ruled by {ml}{win}, so this chapter "
              f"foregrounds {_karaka(ml)}.")
    # natal dignity of the dasha lord meaningfully colours the period
    mlp = by.get(ml)
    if mlp:
        dg = str(mlp.get("dignity", "Normal")).lower()
        if dg in ("exalted", "own sign", "moolatrikona"):
            detail += f" Natally {ml} is {dg}, which strengthens what this period can deliver."
        elif dg == "debilitated":
            detail += f" Natally {ml} is debilitated, so its results ask for patience and conscious effort."
    if al:
        aw = ""
        if cur.get("ad_start") and cur.get("ad_end"):
            aw = f" ({cur['ad_start']} to {cur['ad_end']})"
        detail += f" Within it, the sub-period (Antardasha) of {al}{aw} adds a layer of {_karaka(al)}."
    return [Finding(
        code="DASHA.CURRENT", category="timing", polarity="neutral", weight=9,
        title=f"{ml}{'–' + al if al else ''} period",
        detail=detail,
        evidence=[f"Vimshottari: Mahadasha {ml}" + (f", Antardasha {al}" if al else "")],
    )]


def _yogas(chart) -> list[Finding]:
    out: list[Finding] = []
    yb = chart.get("yogas")
    detected = _l(_d(yb).get("detected")) if isinstance(yb, dict) else _l(yb)
    for y in detected:
        if not isinstance(y, dict):
            continue
        name = y.get("name", "Yoga")
        desc = y.get("description", "a recognised combination")
        out.append(Finding(
            code=f"YOGA.{name.split()[0].upper()}", category="essence",
            polarity="supportive", weight=6,
            title=name,
            detail=f"{name} is present in the chart — classically linked to {desc.lower()}.",
            evidence=[f"{name}: {', '.join(y.get('planets', []))}".strip(": ")],
        ))
    return out


def _retro(by) -> list[Finding]:
    retro = [n for n, p in by.items() if p.get("retrograde") and n not in ("Rahu", "Ketu")]
    if not retro:
        return []
    names = ", ".join(retro)
    is_one = len(retro) == 1
    return [Finding(
        code="MOTION.RETRO", category="mind", polarity="mixed", weight=4,
        title=f"Retrograde: {names}",
        detail=(f"{names} {'is' if is_one else 'are'} retrograde, which classically turns "
                f"{'its' if is_one else 'their'} energy inward — more reflective, revisiting and "
                f"refining {'its' if is_one else 'their'} themes rather than rushing them."),
        evidence=[f"Retrograde: {names}"],
    )]


def _combust(by) -> list[Finding]:
    comb = [n for n, p in by.items() if p.get("combust")]
    if not comb:
        return []
    names = ", ".join(comb)
    return [Finding(
        code="MOTION.COMBUST", category="essence", polarity="challenging", weight=5,
        title=f"Combust: {names}",
        detail=(f"{names} {'is' if len(comb)==1 else 'are'} combust (very close to the Sun), so "
                f"{'its' if len(comb)==1 else 'their'} expression tends to be internalised — strongly "
                f"felt within, less visible outwardly — until consciously developed."),
        evidence=[f"Combust: {names}"],
    )]


def _conjunctions(chart, asc_sign) -> list[Finding]:
    out: list[Finding] = []
    cj = _l(chart.get("conjunctions"))
    for c in cj:
        if not isinstance(c, dict):
            continue
        strength = str(c.get("strength", ""))
        if not (strength.startswith("Very Close") or strength.startswith("Close")):
            continue  # only surface genuinely tight conjunctions
        p1, p2 = c.get("planet_1"), c.get("planet_2")
        if not p1 or not p2:
            continue
        sep = c.get("separation")
        cat = "relationships" if "Venus" in (p1, p2) else "mind" if "Moon" in (p1, p2) else "essence"
        out.append(Finding(
            code=f"CONJ.{p1.upper()}.{p2.upper()}", category=cat, polarity="mixed", weight=6,
            title=f"{p1}–{p2} conjunction",
            detail=(f"{p1} and {p2} sit in close conjunction (about {sep}° apart), blending "
                    f"{_karaka(p1)} with {_karaka(p2)} — these two themes operate together rather "
                    f"than separately in this life."),
            evidence=[f"{p1} conjunct {p2} (~{sep}°)"],
        ))
        if len(out) >= 2:  # keep to the two tightest
            break
    return out


def _atmakaraka(chart) -> list[Finding]:
    ak = _d(_d(chart.get("jaimini_karakas")).get("Atmakaraka"))
    p = ak.get("planet")
    if not p:
        return []
    sign = ak.get("sign")
    return [Finding(
        code="JAIMINI.AK", category="spirit", polarity="neutral", weight=6,
        title=f"Atmakaraka: {p}",
        detail=(f"By Jaimini, the Atmakaraka — the soul significator, the planet at the highest "
                f"degree — is {p}{f' in {sign}' if sign else ''}. It points to {_karaka(p)} as the "
                f"core inner agenda this life keeps returning to."),
        evidence=[f"Atmakaraka: {p}{f' in {sign}' if sign else ''}"],
    )]


def _sade_sati(chart) -> list[Finding]:
    ss = _d(chart.get("sade_sati"))
    if not ss.get("active"):
        return []
    phase = ss.get("phase", "")
    return [Finding(
        code="TRANSIT.SADESATI", category="timing", polarity="challenging", weight=7,
        title="Sade Sati active",
        detail=(f"Saturn's Sade Sati is currently active ({phase}). This well-known ~7.5-year "
                f"transit asks for patience, realism, and consolidation; it tends to mature "
                f"responsibility and clear away what is no longer sustainable."),
        evidence=[f"Sade Sati: {phase}"],
    )]


def _gandanta(chart, by) -> list[Finding]:
    out: list[Finding] = []
    gz = _l(_d(chart.get("danger_zones")).get("gandanta_planets"))
    for g in gz:
        if not isinstance(g, dict):
            continue
        p = g.get("planet")
        if not p:
            continue
        out.append(Finding(
            code=f"GANDANTA.{p.upper()}", category=GRAHA_CATEGORY.get(p, "essence"),
            polarity="mixed", weight=3,
            title=f"{p} at a gandanta degree",
            detail=(f"{p} sits at a gandanta point (a sensitive water–fire sign junction), which can "
                    f"give the matters it rules — {_karaka(p)} — an added depth and intensity that "
                    f"tends to settle and mature with time."),
            evidence=[f"{p} gandanta"],
        ))
    return out


# --------------------------------------------------------------------------- #
# enriched coverage — house lords / karakas so every life-area has substance
# --------------------------------------------------------------------------- #
def _relationships(chart, by, asc_sign) -> list[Finding]:
    out: list[Finding] = []
    if not asc_sign:
        return out
    # 7th-house lord — the primary marriage/partnership indicator
    sign7 = _sign_in_house(asc_sign, 7)
    lord7 = _lord_of(sign7)
    lp = by.get(lord7) if lord7 else None
    if lp and lp.get("sign"):
        hL = _house_ws(lp["sign"], asc_sign)
        sp = _strength_phrase(lp.get("dignity"))
        out.append(Finding(
            code="RELATION.7THLORD", category="relationships", polarity="neutral", weight=7,
            title=f"7th lord {lord7} in the {_ord(hL)} house",
            detail=(f"Partnership and marriage are read from the 7th house ({sign7}), whose lord is "
                    f"{lord7}. {lord7} sits in the {_ord(hL)} house in {lp['sign']}{sp}, so the area "
                    f"of {HOUSE_MEANING.get(hL,'that house')} tends to be woven into how close "
                    f"partnership unfolds."),
            evidence=[f"7th lord {lord7} in {lp['sign']}, {_ord(hL)} house"],
        ))
    # planets sitting in the 7th house
    occ = _occupants(by, asc_sign, 7)
    if occ:
        names = ", ".join(occ)
        kk = "; ".join(f"{n} ({_karaka(n)})" for n in occ)
        out.append(Finding(
            code="RELATION.7THOCC", category="relationships", polarity="mixed", weight=6,
            title=f"{names} in the 7th house",
            detail=(f"{names} occupies the 7th house of partnership, so {'its' if len(occ)==1 else 'their'} "
                    f"significations colour one-to-one relationships directly — {kk}."),
            evidence=[f"In 7th house: {names}"],
        ))
    # Venus — natural significator of love and attraction
    v = by.get("Venus")
    if v and v.get("sign"):
        hV = _house_ws(v["sign"], asc_sign)
        sp = _strength_phrase(v.get("dignity"))
        nak = v.get("nakshatra")
        out.append(Finding(
            code="RELATION.VENUS", category="relationships", polarity="neutral", weight=6,
            title=f"Venus in the {_ord(hV)} house",
            detail=(f"Venus, the natural significator of love and attraction, is in {v['sign']}{sp} in "
                    f"the {_ord(hV)} house" + (f" in {nak}" if nak else "") + f", shaping how affection, "
                    f"beauty and closeness are sought and expressed around "
                    f"{HOUSE_MEANING.get(hV,'that house')}."),
            evidence=[f"Venus in {v['sign']}, {_ord(hV)} house" + (f", {nak}" if nak else "")],
        ))
    # Darakaraka — spouse significator (only if the engine provides it)
    dk = _d(_d(chart.get("jaimini_karakas")).get("Darakaraka"))
    dp = dk.get("planet")
    if dp:
        ds = dk.get("sign")
        out.append(Finding(
            code="RELATION.DK", category="relationships", polarity="neutral", weight=6,
            title=f"Darakaraka: {dp}",
            detail=(f"By Jaimini, the Darakaraka — significator of the spouse, the planet at the lowest "
                    f"degree — is {dp}{f' in {ds}' if ds else ''}. Its nature, {_karaka(dp)}, describes "
                    f"qualities that tend to come forward through partnership."),
            evidence=[f"Darakaraka: {dp}{f' in {ds}' if ds else ''}"],
        ))
    return out


def _career_houses(by, asc_sign) -> list[Finding]:
    out: list[Finding] = []
    if not asc_sign:
        return out
    sign10 = _sign_in_house(asc_sign, 10)
    lord10 = _lord_of(sign10)
    lp = by.get(lord10) if lord10 else None
    if lp and lp.get("sign"):
        hL = _house_ws(lp["sign"], asc_sign)
        sp = _strength_phrase(lp.get("dignity"))
        out.append(Finding(
            code="CAREER.10THLORD", category="career", polarity="neutral", weight=7,
            title=f"10th lord {lord10} in the {_ord(hL)} house",
            detail=(f"Career, status and public action are read from the 10th house ({sign10}), whose "
                    f"lord is {lord10}. {lord10} sits in the {_ord(hL)} house in {lp['sign']}{sp}, "
                    f"linking your work and visible role to {HOUSE_MEANING.get(hL,'that house')}."),
            evidence=[f"10th lord {lord10} in {lp['sign']}, {_ord(hL)} house"],
        ))
    occ = _occupants(by, asc_sign, 10)
    if occ:
        names = ", ".join(occ)
        kk = "; ".join(f"{n} ({_karaka(n)})" for n in occ)
        out.append(Finding(
            code="CAREER.10THOCC", category="career", polarity="mixed", weight=6,
            title=f"{names} in the 10th house",
            detail=(f"{names} occupies the 10th house of career and visible action, bringing "
                    f"{'its' if len(occ)==1 else 'their'} themes into professional life — {kk}."),
            evidence=[f"In 10th house: {names}"],
        ))
    return out


def _mercury_mind(by, asc_sign) -> list[Finding]:
    # Mercury as intellect/communication; skip if it's the lagna lord (already covered in essence)
    if _lord_of(asc_sign) == "Mercury":
        return []
    m = by.get("Mercury")
    if not (m and m.get("sign")):
        return []
    h = _house_ws(m["sign"], asc_sign)
    sp = _strength_phrase(m.get("dignity"))
    nak = m.get("nakshatra")
    return [Finding(
        code="MIND.MERCURY", category="mind", polarity="neutral", weight=5,
        title=f"Mercury in the {_ord(h)} house",
        detail=(f"Mercury — intellect, speech and how the mind processes — is in {m['sign']}{sp} in the "
                f"{_ord(h)} house" + (f" in {nak}" if nak else "") + f", shaping the style of thinking "
                f"and communication around {HOUSE_MEANING.get(h,'that house')}."),
        evidence=[f"Mercury in {m['sign']}, {_ord(h)} house" + (f", {nak}" if nak else "")],
    )]


def _ninth_spirit(by, asc_sign) -> list[Finding]:
    if not asc_sign:
        return []
    sign9 = _sign_in_house(asc_sign, 9)
    lord9 = _lord_of(sign9)
    lp = by.get(lord9) if lord9 else None
    if not (lp and lp.get("sign")):
        return []
    hL = _house_ws(lp["sign"], asc_sign)
    sp = _strength_phrase(lp.get("dignity"))
    return [Finding(
        code="SPIRIT.NINTH", category="spirit", polarity="neutral", weight=5,
        title=f"9th lord {lord9} in the {_ord(hL)} house",
        detail=(f"Belief, meaning and dharma are read from the 9th house ({sign9}), whose lord is "
                f"{lord9}, placed in the {_ord(hL)} house in {lp['sign']}{sp} — connecting your sense "
                f"of faith and guiding principles to {HOUSE_MEANING.get(hL,'that house')}."),
        evidence=[f"9th lord {lord9} in {lp['sign']}, {_ord(hL)} house"],
    )]


# Jaimini Chara Karakas beyond Atmakaraka (handled in _atmakaraka) and Darakaraka
# (handled in _relationships). Each is routed to the section its signification fits,
# with the two "character" karakas steered to thinner sections via their house themes.
_CHARA_KARAKA = {
    "Amatyakaraka": ("career", 6, "career, profession, and the work that carries one's purpose into the world"),
    "Bhratrikaraka": ("mind", 5, "courage, initiative, communication, and siblings"),
    "Matrikaraka": ("mind", 5, "the mother, emotional nourishment, and matters of the heart"),
    "Putrakaraka": ("family", 5, "children, creativity, intelligence, and the fruits of past good karma"),
    "Gnatikaraka": ("career", 5, "service, diligence, rivals, and obstacles met and overcome"),
}
_CHARA_ABBR = {"Amatyakaraka": "AMK", "Bhratrikaraka": "BK", "Matrikaraka": "MK",
               "Putrakaraka": "PK", "Gnatikaraka": "GK"}


def _chara_karakas(chart, by, asc_sign) -> list[Finding]:
    out: list[Finding] = []
    kk = _d(chart.get("jaimini_karakas"))
    for name, (cat, wt, sig) in _CHARA_KARAKA.items():
        entry = _d(kk.get(name))
        p = entry.get("planet")
        if not p:
            continue
        sign = entry.get("sign")
        lp = by.get(p) or {}
        house = _house_ws(sign or lp.get("sign"), asc_sign)
        sp = _strength_phrase(lp.get("dignity"))
        where = f" in the {_ord(house)} house" if house else ""
        out.append(Finding(
            code=f"JAIMINI.{_CHARA_ABBR[name]}", category=cat, polarity="neutral", weight=wt,
            title=f"{name}: {p}",
            detail=(f"By Jaimini, the {name} — a chara karaka derived from planetary degree — is "
                    f"{p}{f' in {sign}' if sign else ''}{where}{sp}. It signifies {sig}, a thread the "
                    f"chart asks you to develop."),
            evidence=[f"{name}: {p}{f' in {sign}' if sign else ''}"],
        ))
    return out


# Chaldean numerology — read straight from the engine's numerology block.
_NUM_SINGLE = {
    1: ("the Sun", "individuality, leadership, and initiative"),
    2: ("the Moon", "sensitivity, cooperation, and a receptive mind"),
    3: ("Jupiter", "expression, optimism, and a drive to learn and teach"),
    4: ("Rahu", "an unconventional, systems-minded, reform-driven streak"),
    5: ("Mercury", "communication, adaptability, and quick intelligence"),
    6: ("Venus", "harmony, relationship, and an eye for beauty and comfort"),
    7: ("Ketu", "introspection, intuition, and a pull toward the inner life"),
    8: ("Saturn", "discipline, responsibility, and mastery built slowly over time"),
    9: ("Mars", "energy, courage, and a competitive drive"),
    11: ("the master number 11", "heightened intuition, idealism, and a sensitive nervous system"),
    22: ("the master number 22", "the master-builder capacity to turn vision into structure"),
    33: ("the master number 33", "the master-teacher capacity for compassionate guidance"),
}


def _numerology(chart) -> list[Finding]:
    n = _d(chart.get("numerology"))
    out: list[Finding] = []
    psy = n.get("psychic")
    if psy in _NUM_SINGLE:
        planet, q = _NUM_SINGLE[psy]
        out.append(Finding(
            code="NUM.PSYCHIC", category="numbers", polarity="neutral", weight=6,
            title=f"Psychic number {psy}",
            detail=(f"In Chaldean numerology the psychic number, taken from the birth day, is {psy} — "
                    f"linked to {planet}: {q}. It describes the instinctive self and how one tends to "
                    f"act on first impulse."),
            evidence=[f"Psychic number {psy} (birth day {n.get('birth_day')})"],
        ))
    des = n.get("destiny")
    if des in _NUM_SINGLE:
        planet, q = _NUM_SINGLE[des]
        out.append(Finding(
            code="NUM.DESTINY", category="numbers", polarity="neutral", weight=7,
            title=f"Destiny number {des}",
            detail=(f"The destiny number, taken from the full date of birth, is {des} — linked to "
                    f"{planet}: {q}. It points to the broad direction life tends to pull toward."),
            evidence=[f"Destiny number {des}"],
        ))
    comp = n.get("name_compound")
    red = n.get("name_reduced")
    meaning = n.get("compound_meaning")
    if comp:
        base = _NUM_SINGLE.get(red)
        red_txt = (f", reducing to {red}" + (f" ({base[1]})" if base else "")) if red else ""
        mean_txt = f" In this tradition the compound {comp} is associated with the theme of “{meaning}.”" if meaning else ""
        out.append(Finding(
            code="NUM.NAME", category="numbers", polarity="neutral", weight=6,
            title=f"Name number {comp}" + (f"/{red}" if red else ""),
            detail=(f"The name read in the Chaldean system totals {comp}{red_txt}.{mean_txt} This is taken "
                    f"as the vibration a name carries in how others meet you — descriptive of reputation, "
                    f"not a fixed fate."),
            evidence=[f"Name compound {comp}" + (f", reduced {red}" if red else "")],
        ))
    return out


def _dasha_upcoming(chart) -> list[Finding]:
    cur = _dasha_current(chart)
    ml = cur.get("mahadasha")
    md_end = cur.get("md_end")
    vim = _d(_d(chart.get("dasha_systems")).get("vimshottari"))
    seq = _l(vim.get("sequence"))
    if not (ml and seq):
        return []
    nxt = None
    for i, row in enumerate(seq):
        if isinstance(row, dict) and row.get("planet") == ml and row.get("start") == cur.get("md_start"):
            if i + 1 < len(seq):
                nxt = seq[i + 1]
            break
    if not nxt and md_end:  # fallback: first period starting on/after the current one's end
        for row in seq:
            if isinstance(row, dict) and str(row.get("start")) >= str(md_end):
                nxt = row
                break
    if not nxt:
        return []
    np_, ns, ne = nxt.get("planet"), nxt.get("start"), nxt.get("end")
    return [Finding(
        code="DASHA.NEXT", category="timing", polarity="neutral", weight=7,
        title=f"Next chapter: {np_} period",
        detail=(f"After the current {ml} period ends (around {md_end}), a major {np_} chapter begins, "
                f"running roughly {ns} to {ne}. The long arc then shifts toward {_karaka(np_)} — worth "
                f"knowing now, so the coming years can be prepared for rather than met by surprise."),
        evidence=[f"Vimshottari next Mahadasha: {np_} ({ns} to {ne})"],
    )]


# --------------------------------------------------------------------------- #
# helpers for the expanded Maha-Kundali coverage
# --------------------------------------------------------------------------- #
def _dignity_of(planet: str | None, sign: str | None) -> str:
    """Dignity of a planet in a given sign — used for divisional (varga) charts."""
    si = _sidx(sign)
    if si is None or not planet:
        return "Normal"
    s1 = si + 1
    ex = EXALT_SIGN.get(planet)
    if ex == s1:
        return "Exalted"
    if ex and (((ex - 1 + 6) % 12) + 1) == s1:
        return "Debilitated"
    if s1 in OWN_SIGNS.get(planet, []):
        return "Own Sign"
    return "Normal"


def _saham(chart, name: str) -> dict:
    s = _d(_d(chart.get("sahams")).get("sahams")).get(name)
    return s if isinstance(s, dict) else {}


_HARSH_STAR = ("violence", "death", "decapitation", "misfortune", "danger", "accident", "assassination", "destruct")


def _star_meaning(m: str | None) -> str:
    ml = (m or "").lower()
    if any(w in ml for w in _HARSH_STAR):
        return "an intense star traditionally said to ask for groundedness and care"
    return m or "a notable fixed star"


def _house_lord_finding(by, asc_sign, house, code, category, weight, lead) -> Finding | None:
    if not asc_sign:
        return None
    sign_h = _sign_in_house(asc_sign, house)
    lord = _lord_of(sign_h)
    lp = by.get(lord) if lord else None
    if not (lp and lp.get("sign")):
        return None
    hL = _house_ws(lp["sign"], asc_sign)
    sp = _strength_phrase(lp.get("dignity"))
    return Finding(
        code=code, category=category, polarity="neutral", weight=weight,
        title=f"{_ord(house)} lord {lord} in the {_ord(hL)} house",
        detail=(f"{lead} ({sign_h}), whose lord is {lord}, placed in the {_ord(hL)} house in "
                f"{lp['sign']}{sp} — connecting it to {HOUSE_MEANING.get(hL,'that house')}."),
        evidence=[f"{_ord(house)} lord {lord} in {lp['sign']}, {_ord(hL)} house"],
    )


def _house_occ_finding(by, asc_sign, house, code, category, weight, label) -> Finding | None:
    occ = _occupants(by, asc_sign, house)
    if not occ:
        return None
    names = ", ".join(occ)
    kk = "; ".join(f"{n} ({_karaka(n)})" for n in occ)
    return Finding(
        code=code, category=category, polarity="mixed", weight=weight,
        title=f"{names} in the {_ord(house)} house",
        detail=(f"{names} occupies the {_ord(house)} house of {label}, bringing "
                f"{'its' if len(occ)==1 else 'their'} themes there — {kk}."),
        evidence=[f"In {_ord(house)} house: {names}"],
    )


# --------------------------------------------------------------------------- #
# new life-area sections
# --------------------------------------------------------------------------- #
def _wealth(chart, by, asc_sign) -> list[Finding]:
    out: list[Finding] = []
    f2 = _house_lord_finding(by, asc_sign, 2, "WEALTH.SECOND", "wealth", 7,
                             "Earnings, savings and family wealth are read from the 2nd house")
    if f2:
        out.append(f2)
    f11 = _house_lord_finding(by, asc_sign, 11, "WEALTH.ELEVENTH", "wealth", 6,
                              "Gains, income and fulfilment of desires are read from the 11th house")
    if f11:
        out.append(f11)
    indu = _d(chart.get("indu_lagna"))
    if indu.get("sign"):
        out.append(Finding(
            code="WEALTH.INDU", category="wealth", polarity="neutral", weight=5,
            title=f"Indu Lagna in {indu['sign']}",
            detail=(f"The Indu Lagna — a special point for wealth and prosperity — falls in "
                    f"{indu['sign']}. Planets placed in or aspecting this sign are read as switches "
                    f"for financial flow."),
            evidence=[f"Indu Lagna: {indu['sign']}"],
        ))
    dh = _saham(chart, "Dhana")
    if dh.get("sign"):
        out.append(Finding(
            code="WEALTH.DHANA", category="wealth", polarity="neutral", weight=3,
            title=f"Dhana Saham in {dh['sign']}",
            detail=(f"The Dhana Saham, a fortuna-style point for wealth, falls in {dh['sign']} — a "
                    f"supplementary marker for where money matters concentrate."),
            evidence=[f"Dhana Saham: {dh['sign']}"],
        ))
    return out


def _family(chart, by, asc_sign) -> list[Finding]:
    out: list[Finding] = []
    f4 = _house_lord_finding(by, asc_sign, 4, "FAMILY.FOURTH", "family", 7,
                             "Home, mother, property and emotional roots are read from the 4th house")
    if f4:
        out.append(f4)
    o4 = _house_occ_finding(by, asc_sign, 4, "FAMILY.FOURTHOCC", "family", 6,
                            "home, mother and emotional foundations")
    if o4:
        out.append(o4)
    f5 = _house_lord_finding(by, asc_sign, 5, "FAMILY.FIFTH", "family", 6,
                             "Children, creativity and intelligence are read from the 5th house")
    if f5:
        out.append(f5)
    pu = _saham(chart, "Putra")
    if pu.get("sign"):
        out.append(Finding(
            code="FAMILY.PUTRA", category="family", polarity="neutral", weight=3,
            title=f"Putra Saham in {pu['sign']}",
            detail=(f"The Putra Saham, a point for children, falls in {pu['sign']} — a supplementary "
                    f"marker for that theme."),
            evidence=[f"Putra Saham: {pu['sign']}"],
        ))
    return out


def _health(chart, by, asc_sign) -> list[Finding]:
    # Astrological wellness tendencies only — not medical guidance. Kept gentle and hedged.
    out: list[Finding] = []
    f6 = _house_lord_finding(by, asc_sign, 6, "HEALTH.SIXTH", "health", 6,
                             "Health, immunity, routine and the capacity to overcome illness are read from the 6th house")
    if f6:
        out.append(f6)
    o6 = _house_occ_finding(by, asc_sign, 6, "HEALTH.SIXTHOCC", "health", 5,
                            "health, work and obstacles overcome")
    if o6:
        out.append(o6)
    # a gentle vitality note from chart-ruler / Moon condition, framed as lifestyle tendency
    asc_lord = _lord_of(asc_sign)
    lp = by.get(asc_lord) if asc_lord else None
    if lp:
        dig = str(lp.get("dignity", "Normal")).lower()
        tone = ("a resilient baseline to maintain with steady habits" if dig in ("exalted", "own sign", "moolatrikona")
                else "a baseline that rewards disciplined routine, rest and stress management"
                if dig == "debilitated" else "a baseline supported by regular rhythm and rest")
        out.append(Finding(
            code="HEALTH.VITALITY", category="health", polarity="neutral", weight=4,
            title="Vitality and routine",
            detail=(f"Overall vitality tracks the chart ruler {asc_lord}; here that suggests {tone}. "
                    f"This is a wellness tendency, not a diagnosis — physical concerns belong with a doctor."),
            evidence=[f"Chart ruler {asc_lord} condition"],
        ))
    return out


def _fortune(chart) -> list[Finding]:
    out: list[Finding] = []
    ya = _d(chart.get("yogi_avayogi"))
    if ya.get("yogi_lord"):
        out.append(Finding(
            code="FORTUNE.YOGI", category="fortune", polarity="supportive", weight=6,
            title=f"Yogi planet {ya.get('yogi_lord')}",
            detail=(f"In the Yogi/Avayogi scheme the Yogi (prosperity) planet is {ya.get('yogi_lord')}"
                    + (f" via {ya.get('yogi_nakshatra')} nakshatra" if ya.get('yogi_nakshatra') else "")
                    + (f", while the Avayogi (friction) lord is {ya.get('avayogi_lord')}" if ya.get('avayogi_lord') else "")
                    + ". The Yogi's periods and placements tend to open doors; the Avayogi's ask for extra care."),
            evidence=[f"Yogi {ya.get('yogi_lord')}, Avayogi {ya.get('avayogi_lord')}"],
        ))
    bb = _d(chart.get("bhrigu_bindu"))
    if bb.get("sign"):
        out.append(Finding(
            code="FORTUNE.BHRIGU", category="fortune", polarity="neutral", weight=5,
            title=f"Bhrigu Bindu in {bb['sign']}",
            detail=(f"The Bhrigu Bindu — a sensitive destiny point (the midpoint of Moon and Rahu) — sits "
                    f"in {bb['sign']}" + (f", {bb.get('nakshatra')}" if bb.get('nakshatra') else "")
                    + ". Transits and dashas touching this point often coincide with pivotal turns."),
            evidence=[f"Bhrigu Bindu: {bb['sign']}"],
        ))
    pn = _saham(chart, "Punya")
    if pn.get("sign"):
        out.append(Finding(
            code="FORTUNE.PUNYA", category="fortune", polarity="supportive", weight=4,
            title=f"Punya Saham in {pn['sign']}",
            detail=(f"The Punya Saham, a point for merit and good fortune, falls in {pn['sign']} — a "
                    f"supplementary marker for where grace tends to accrue."),
            evidence=[f"Punya Saham: {pn['sign']}"],
        ))
    return out


def _strengths(chart) -> list[Finding]:
    out: list[Finding] = []
    sb = _d(chart.get("shadbala"))
    items = [(p, v.get("rupas")) for p, v in sb.items()
             if isinstance(v, dict) and isinstance(v.get("rupas"), (int, float))]
    if items:
        items.sort(key=lambda x: -x[1])
        s, w = items[0], items[-1]
        out.append(Finding(
            code="STRENGTH.SHADBALA", category="strengths", polarity="neutral", weight=6,
            title=f"Strongest planet: {s[0]}",
            detail=(f"By Shadbala (the six-fold strength measure), {s[0]} is the strongest planet in the "
                    f"chart (about {s[1]} rupas) and {w[0]} the weakest (about {w[1]}). The strongest "
                    f"planet's significations tend to act with the most reliable force."),
            evidence=[f"Shadbala: strongest {s[0]} ({s[1]}), weakest {w[0]} ({w[1]})"],
        ))
    av = _d(chart.get("ashtakavarga"))
    sh, wk = _l(av.get("strong_houses")), _l(av.get("weak_houses"))
    if sh or wk:
        sh_t = ", ".join(_ord(h) for h in sh) or "—"
        wk_t = ", ".join(_ord(h) for h in wk) or "—"
        out.append(Finding(
            code="STRENGTH.AV", category="strengths", polarity="neutral", weight=5,
            title="Ashtakavarga strong and weak houses",
            detail=(f"In the Ashtakavarga point-count the strongest houses are the {sh_t}, and the leaner "
                    f"ones the {wk_t}. Effort tends to be best rewarded in the strong houses, while the "
                    f"lean ones ask for more deliberate support."),
            evidence=[f"Ashtakavarga strong {sh}, weak {wk}"],
        ))
    fs = _l(chart.get("fixed_stars"))
    notable = [s for s in fs if isinstance(s, dict) and s.get("planet") in ("Ascendant", "Moon", "Sun")]
    if notable:
        s0 = notable[0]
        out.append(Finding(
            code="STRENGTH.STAR", category="strengths", polarity="neutral", weight=4,
            title=f"{s0.get('star')} close to your {s0.get('planet')}",
            detail=(f"The fixed star {s0.get('star')} sits close to your {s0.get('planet')} "
                    f"(orb about {s0.get('orb')}°) — {_star_meaning(s0.get('meaning'))}."),
            evidence=[f"{s0.get('star')} conjunct {s0.get('planet')} (orb {s0.get('orb')}°)"],
        ))
    return out


def _kp(chart) -> list[Finding]:
    out: list[Finding] = []
    cusps = _d(_d(chart.get("kp_significators")).get("cusps"))
    spec = [(7, "marriage and partnership"), (10, "career and public standing"),
            (2, "wealth and family"), (11, "gains and the fulfilment of desires")]
    for h, label in spec:
        c = _d(cusps.get(f"H{h}"))
        sub = c.get("sub")
        if not sub:
            continue
        out.append(Finding(
            code=f"KP.H{h}", category="kp", polarity="neutral", weight=5,
            title=f"KP {_ord(h)}-cusp sub-lord: {sub}",
            detail=(f"In KP (Krishnamurti Paddhati), the sub-lord of the {_ord(h)} cusp — which governs "
                    f"{label} — is {sub}. KP reads the outcome and timing of {label} chiefly from "
                    f"{sub}'s house-significations and dasha, so {sub} is the planet to watch for that area."),
            evidence=[f"KP {_ord(h)} cusp sub-lord {sub}"],
        ))
    return out


def _panchang(chart) -> list[Finding]:
    out: list[Finding] = []
    p = _d(chart.get("panchang"))
    ti, va, nk, yo, ka = (_d(p.get("tithi")), _d(p.get("vara")), _d(p.get("nakshatra")),
                          _d(p.get("yoga")), _d(p.get("karana")))
    if va.get("name") and nk.get("name"):
        out.append(Finding(
            code="PANCHANG.BIRTH", category="panchang", polarity="neutral", weight=5,
            title=f"Born on {va.get('name')}, {nk.get('name')} nakshatra",
            detail=(f"You were born on a {va.get('name')} ({va.get('lord')}'s day), in the "
                    f"{ti.get('paksha')} fortnight on {ti.get('name')} tithi, under {nk.get('name')} "
                    f"nakshatra (pada {nk.get('pada')}, lord {nk.get('lord')}), with {yo.get('name')} "
                    f"yoga and {ka.get('name')} karana — the living energies of the day at your first breath."),
            evidence=[f"{va.get('name')}, {ti.get('name')} tithi, {nk.get('name')} nakshatra"],
        ))
    mp = _d(chart.get("moon_phase"))
    if mp.get("phase_name"):
        out.append(Finding(
            code="PANCHANG.MOON", category="panchang", polarity="neutral", weight=4,
            title=f"{mp.get('phase_name')} at birth",
            detail=(f"The Moon was at the {mp.get('phase_name')} (about {mp.get('illumination_pct')}% lit, "
                    f"{'waxing' if mp.get('waxing') else 'waning'}) — "
                    f"{'a building, outgoing lunar phase' if mp.get('waxing') else 'a culminating, reflective lunar phase'}."),
            evidence=[f"Moon phase: {mp.get('phase_name')}"],
        ))
    ho = _d(chart.get("hora"))
    if ho.get("hora_lord"):
        out.append(Finding(
            code="PANCHANG.HORA", category="panchang", polarity="neutral", weight=3,
            title=f"Birth hora of {ho.get('hora_lord')}",
            detail=(f"The planetary hour (hora) at birth was ruled by {ho.get('hora_lord')}, lending that "
                    f"planet's tone to the very hour you arrived."),
            evidence=[f"Birth hora: {ho.get('hora_lord')}"],
        ))
    return out


def _alerts(chart, by) -> list[Finding]:
    raw = _d(_cb(chart).get("planets"))

    def st(p):
        return _d(_d(raw.get(p)).get("status"))

    gand = [p for p in raw if st(p).get("gandanta")]
    debil = [p for p in raw if str(st(p).get("dignity", "")).lower() == "debilitated"]
    retro = [p for p in raw if st(p).get("retrograde") and p not in ("Rahu", "Ketu")]
    comb = [p for p in raw if st(p).get("combust")]
    mb = [p for p in raw if st(p).get("mrityu_bhaga")]
    flags: list[str] = []
    if gand:
        flags.append(f"{', '.join(gand)} at a gandanta (sign-junction) degree")
    if debil:
        flags.append(f"{', '.join(debil)} debilitated")
    if retro:
        flags.append(f"{', '.join(retro)} retrograde")
    if comb:
        flags.append(f"{', '.join(comb)} combust (very close to the Sun)")
    if mb:
        flags.append(f"{', '.join(mb)} at a Mrityu Bhaga (sensitive) degree")
    if _l(chart.get("planetary_wars")):
        flags.append("a planetary war (graha yuddha) between two close planets")
    ecl = _d(chart.get("eclipse_proximity"))
    if ecl.get("solar_eclipse_proximity") or ecl.get("lunar_eclipse_proximity"):
        flags.append("an eclipse close to the time of birth")
    if not flags:
        return []
    return [Finding(
        code="ALERTS.SUMMARY", category="alerts", polarity="mixed", weight=5,
        title="Sensitive points to handle with awareness",
        detail=("Points worth handling with awareness rather than alarm: " + "; ".join(flags) +
                ". These are the chart's tender spots — areas that tend to mature with patience and "
                "conscious care rather than force, and they are noted here for steadiness, not fear."),
        evidence=["; ".join(flags)],
    )]


_REMEDY = {
    "Sun": ("the Surya mantra (ॐ सूर्याय नमः) on Sundays", "spend time in early-morning sunlight and lead without ego"),
    "Moon": ("the Chandra mantra (ॐ सोमाय नमः) on Mondays", "keep a steady sleep and hydration rhythm and tend your emotional rest"),
    "Mars": ("the Hanuman Chalisa on Tuesdays", "channel energy through exercise before reacting in conflict"),
    "Mercury": ("the Budha mantra (ॐ बुधाय नमः) on Wednesdays", "keep a daily writing or planning habit"),
    "Jupiter": ("the Guru mantra (ॐ गुरवे नमः) on Thursdays", "study, teach, and give time to mentors and students"),
    "Venus": ("the Shukra mantra (ॐ शुक्राय नमः) on Fridays", "tend relationships and beauty without overindulgence"),
    "Saturn": ("the Shani mantra (ॐ शं शनैश्चराय नमः) on Saturdays", "serve elders and workers, and keep patient routine"),
    "Rahu": ("the Rahu mantra (ॐ रां राहवे नमः)", "favour clear, honest routines over shortcuts and ground big ambitions"),
    "Ketu": ("the Ketu mantra (ॐ कें केतवे नमः)", "give time to silence, meditation, and letting go"),
}


def _remedies(chart, by) -> list[Finding]:
    raw = _d(_cb(chart).get("planets"))

    def st(p):
        return _d(_d(raw.get(p)).get("status"))

    targets: list[tuple[str, str]] = []
    for p in raw:
        s = st(p)
        if str(s.get("dignity", "")).lower() == "debilitated" or s.get("combust"):
            targets.append((p, "to support a tender placement"))
    ml = _dasha_current(chart).get("mahadasha")
    if ml:
        targets.append((ml, "to align with the current major period"))
    if _d(chart.get("sade_sati")).get("active"):
        targets.append(("Saturn", "through the current Sade Sati"))
    out: list[Finding] = []
    seen: set[str] = set()
    for p, why in targets:
        if p not in _REMEDY or p in seen:
            continue
        seen.add(p)
        mantra, beh = _REMEDY[p]
        out.append(Finding(
            code=f"REMEDY.{p.upper()}", category="remedies", polarity="supportive", weight=4,
            title=f"For {p}",
            detail=(f"Traditional, optional supports for {p} {why}: chant {mantra}; in daily life, {beh}. "
                    f"These are supportive practices offered in the tradition — not requirements, "
                    f"directives, or guarantees of outcome."),
            evidence=[f"Remedy for {p} ({why})"],
        ))
        if len(out) >= 4:
            break
    if out:
        out.append(Finding(
            code="REMEDY.NOTE", category="remedies", polarity="neutral", weight=2,
            title="A note on gemstones",
            detail=("Gemstones are not suggested casually — a stone over-amplifies its planet and should "
                    "only follow a personal consultation with a qualified astrologer. Behavioural and "
                    "devotional remedies are gentler and carry no such risk."),
            evidence=["Gemstone caution"],
        ))
    return out


# enrichments that feed existing sections (arudha, navamsa, dasamsa, transit, sahams)
def _arudha(chart) -> list[Finding]:
    out: list[Finding] = []
    ar = _d(chart.get("arudha_padas"))
    al = _d(ar.get("AL")).get("sign")
    ul = _d(ar.get("UL")).get("sign")
    if al:
        out.append(Finding(
            code="ESSENCE.AL", category="essence", polarity="neutral", weight=5,
            title=f"Arudha Lagna in {al}",
            detail=(f"Your Arudha Lagna — the chart's projected image, how the world tends to perceive you "
                    f"— falls in {al}. People often meet you through that sign's colours, even where your "
                    f"inner reality runs differently."),
            evidence=[f"Arudha Lagna: {al}"],
        ))
    if ul:
        out.append(Finding(
            code="RELATION.UL", category="relationships", polarity="neutral", weight=6,
            title=f"Upapada Lagna in {ul}",
            detail=(f"The Upapada Lagna (UL), the Jaimini marker of marriage and the spouse, is in {ul}; "
                    f"its sign sets a key signature for the texture of committed partnership."),
            evidence=[f"Upapada Lagna: {ul}"],
        ))
    return out


def _navamsa(chart) -> list[Finding]:
    d9 = _d(_d(chart.get("vargas")).get("D9"))
    lag = _d(d9.get("Lagna")).get("sign")
    ven = _d(d9.get("Venus")).get("sign")
    if not (lag or ven):
        return []
    bits = []
    if lag:
        bits.append(f"the navamsa ascendant is {lag}")
    if ven:
        bits.append(f"Venus is in {ven}{_strength_phrase(_dignity_of('Venus', ven))}")
    return [Finding(
        code="RELATION.D9", category="relationships", polarity="neutral", weight=6,
        title="Navamsa (D9) — the marriage chart",
        detail=("In the navamsa (D9), the classical chart of marriage and inner dharma, " +
                " and ".join(bits) + ". The navamsa refines how partnership and commitment mature "
                "beneath the surface chart."),
        evidence=[f"D9: Lagna {lag}, Venus {ven}"],
    )]


def _dasamsa(chart) -> list[Finding]:
    d10 = _d(_d(chart.get("vargas")).get("D10"))
    lag = _d(d10.get("Lagna")).get("sign")
    if not lag:
        return []
    return [Finding(
        code="CAREER.D10", category="career", polarity="neutral", weight=5,
        title="Dasamsa (D10) — the career chart",
        detail=(f"In the dasamsa (D10), the chart of career and visible action, the ascendant is {lag} — "
                f"refining the field and public shape that professional life tends to take."),
        evidence=[f"D10 ascendant: {lag}"],
    )]


def _double_transit(chart) -> list[Finding]:
    dt = _d(chart.get("double_transit"))
    houses = [h for h in _l(dt.get("houses")) if isinstance(h, int)]
    if not (dt.get("active") and houses):
        return []
    hs = ", ".join(_ord(h) for h in houses)
    return [Finding(
        code="TIMING.DBL", category="timing", polarity="supportive", weight=6,
        title=f"Double transit on the {hs} house",
        detail=(f"A Saturn–Jupiter double transit is currently active over the {hs} house — a recognised "
                f"activation window, when the matters of that house tend to come forward for real "
                f"development and decisions."),
        evidence=[f"Double transit active: {hs} house"],
    )]


def _twelfth_spirit(chart, by, asc_sign) -> list[Finding]:
    f12 = _house_lord_finding(by, asc_sign, 12, "SPIRIT.TWELFTH", "spirit", 5,
                              "Retreat, foreign lands, rest, expenditure and liberation are read from the 12th house")
    return [f12] if f12 else []


def _section_sahams(chart) -> list[Finding]:
    out: list[Finding] = []
    for nm, topic, cat, code in [
        ("Vivaha", "marriage", "relationships", "RELATION.VIVAHA"),
        ("Karma", "profession", "career", "CAREER.KARMA"),
        ("Sadhana", "spiritual practice", "spirit", "SPIRIT.SADHANA"),
    ]:
        s = _saham(chart, nm)
        if s.get("sign"):
            out.append(Finding(
                code=code, category=cat, polarity="neutral", weight=3,
                title=f"{nm} Saham in {s['sign']}",
                detail=(f"The {nm} Saham, a fortuna-style point for {topic}, falls in {s['sign']} — a "
                        f"supplementary marker for that area of life."),
                evidence=[f"{nm} Saham: {s['sign']}"],
            ))
    return out


# --------------------------------------------------------------------------- #
# public
# --------------------------------------------------------------------------- #
def derive_findings(chart: dict[str, Any]) -> list[Finding]:
    planets = _planets(chart)
    by = _by_name(planets)
    asc_sign = _asc_sign(chart)

    findings: list[Finding] = []
    findings += _lagna(chart, by, asc_sign)
    findings += _dignities(by, asc_sign)
    findings += _moon_nakshatra(chart, by, asc_sign)
    findings += _dasha(chart, by)
    findings += _yogas(chart)
    findings += _retro(by)
    findings += _combust(by)
    findings += _conjunctions(chart, asc_sign)
    findings += _atmakaraka(chart)
    findings += _sade_sati(chart)
    findings += _gandanta(chart, by)
    # enriched coverage so each life-area section has grounded substance
    findings += _relationships(chart, by, asc_sign)
    findings += _career_houses(by, asc_sign)
    findings += _mercury_mind(by, asc_sign)
    findings += _ninth_spirit(by, asc_sign)
    findings += _chara_karakas(chart, by, asc_sign)
    findings += _numerology(chart)
    findings += _dasha_upcoming(chart)
    # full Maha-Kundali coverage
    findings += _wealth(chart, by, asc_sign)
    findings += _family(chart, by, asc_sign)
    findings += _health(chart, by, asc_sign)
    findings += _fortune(chart)
    findings += _strengths(chart)
    findings += _kp(chart)
    findings += _panchang(chart)
    findings += _alerts(chart, by)
    findings += _remedies(chart, by)
    findings += _arudha(chart)
    findings += _navamsa(chart)
    findings += _dasamsa(chart)
    findings += _double_transit(chart)
    findings += _twelfth_spirit(chart, by, asc_sign)
    findings += _section_sahams(chart)

    findings.sort(key=lambda f: (-f.weight, f.code))
    return findings
