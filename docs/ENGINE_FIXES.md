# Engine correctness fixes (2026-06) — from beta feedback

A Reddit beta tester reported: (1) D10 chart wrong, (2) Mercury falsely in Mrityu Bhaga,
(3) chat answers too general. Root causes + fixes below.

> NOTE: the real fixes for (1) and (2) live in the **proprietary engine**
> `api/maha_jyotish_cloud_engine.py`, which is **gitignored and not in this repo**. They
> exist only in the local copy that is uploaded to Cloud Build at deploy. This file is the
> committed record so the change isn't lost. The mock engine (`app/mock_engine.py`) and the
> chat prompt (`app/llm.py`) ARE in the repo and were updated to match.

## 1. Divisional charts (D10 and others) were wrong — FIXED
`varga_position()` computed **every** varga with one generic cyclic formula:
`new_sign = (sign*div + part) % 12`. That is only correct for **D1** and **D9 (navamsa)**.
Each varga has its own classical Parashari mapping, so D10/D3/D7/D12/D24/D30/... were wrong.
Example: **D10 (Dasamsa)** — odd signs start from the sign itself, **even signs start from the
9th** sign; the old formula started even signs one sign too far (e.g. a planet at 5° Taurus
gave Pisces instead of the correct **Aquarius**).

Rewrote `varga_position()` with the correct per-varga rules:
- D2 Hora (Leo/Cancer halves), D3 Drekkana (1/5/9), D4 (kendras), D7 (odd→sign/even→7th),
  D9 (cardinal→sign, fixed→9th, dual→5th — unchanged, verified no regression),
  D10 (odd→sign/even→9th), D12 (from sign), D16 (movable Aries/fixed Leo/dual Sag),
  D20 (Aries/Sag/Leo), D24 (odd→Leo/even→Cancer), D27 (by element), D30 Trimsamsa (5 UNEQUAL
  parts to fixed signs), D40 (odd→Aries/even→Libra), D45 (Aries/Leo/Sag), D60 (from sign).
- Verified against hand-computed classical values (D9 start signs, D10 even-sign mapping,
  D24, Drekkana 1/5/9, D12). All pass.

## 2. Mrityu Bhaga over-reported — FIXED
`check_mrityu_bhaga()` flagged a planet within **±1° (a 2° window)** of the sensitive degree,
so planets merely *near* the degree (like the user's Mercury) were wrongly flagged. Mrityu
Bhaga is a single sensitive degree; the "Nth degree" is the span **[N−1, N)**. Tightened the
test to `(mb_deg - 1) <= sign_deg < mb_deg`. (The degree table itself was unchanged.)

## 3. Chat answers too general — IMPROVED
`CHAT_SYSTEM_PROMPT` in `app/llm.py` now makes specificity a hard requirement: every answer
must name a concrete placement (planet, sign, house, and where it sharpens the point the exact
degree, nakshatra/pada or dignity), and timing questions must cite the current
Mahadasha–Antardasha with its end date from CHART_FACTS. Answers that could apply to any chart
are rejected. (CHART_FACTS already supplied this data; the model just wasn't pushed to use it.)

## Cache
`ENGINE_VERSION` bumped `maha-jyotish-7.0 → 7.1` on the live service, which is part of both the
chart and reading cache keys — so corrected charts are recomputed, not served stale.
