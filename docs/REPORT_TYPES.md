# docs/REPORT_TYPES.md — Report types, modes, and tabs

The five CustomGPT "cards" are two different things. Don't build five identical tabs when three share
one engine call.

## A) Report types — same birth-details flow, different section-set

These all `POST /v1/reading` with the user's birth details and differ only in *which sections* come
back. Implement as a `report_type` field on the existing reading flow; the section-set is chosen by
`report_type` ∩ the tier's unlocked sections.

| report_type | sections | min tier |
|-------------|----------|----------|
| `natal` | essence, mind, relationships, career, timing, spirit | basic |
| `maha_kundali` | all 16 | pro |
| `yearly` (Varshphal) | a year-scoped set: a new **yearly** section + timing, fortune, alerts (computed for `year`) | pro |

Backend changes:
- Add `report_type: Literal["natal","maha_kundali","yearly"] = "maha_kundali"` to the reading request.
- A mapping `REPORT_SECTIONS[report_type] -> frozenset[str]`. Effective sections =
  `REPORT_SECTIONS[report_type] & tier.sections`. (So a Basic user requesting `maha_kundali` still only
  gets their 5 unlocked sections — the tab is visible but content is gated. Show an upgrade nudge.)
- `report_type` is part of the **cache key** (alongside the version stamps + sections).
- For `yearly`: take a `year` param, compute the chart, then a `_yearly(chart, year)` generator reads
  `dasha_systems.vimshottari` (the antardasha/pratyantardasha active across that year) + `double_transit`
  + `planetary_ingress` to produce timing-forward findings in a new `yearly` category. Bump `RULES_VERSION`.

Frontend: tabs **Natal**, **Maha-Kundali**, **Yearly** all reuse one `<BirthForm/>` + `<Reading/>`;
they differ by the `report_type` they send (and Yearly adds a year picker). Locked tabs (tier too low)
render a paywall card instead of the form.

## B) Interactive modes — different inputs, their own endpoints

These do **not** take a birth-time-based natal flow; each is its own endpoint + form + renderer.

### Prashna / KP horary — `POST /v1/prashna`
- Input: `{question, lat, lon, tz}` (+ optional category). Chart is cast for **now** (the moment of
  asking), not a birth time.
- Logic: KP 4-step on the relevant house's cuspal sub-lord (`kp_significators.cusps`), mapped from the
  question (7=marriage, 10=career, 6=job, 2/11=money, ...). **Premise neutrality**: if the user states an
  event as fact, do not assume it true — give the KP read plus a "if not, here's the alternative" branch.
  Never invent specifics not in the chart.
- Output: a grounded verdict reading (favourable/challenging/mixed + the sub-lord reasoning + timing by
  sign modality), same `ReadingResponse` shape, with findings in a `prashna` category.
- Tier: pro+. (KP horary is a premium, interactive feature.)

### Birth-Time Rectification — `POST /v1/btr`
- Input: `{name, dob, tob, lat, lon, tz, gender, sunrise_time, events:[{date,type}]}`.
- Logic: call the engine's `rectify_birth_time(...)` (it returns candidate times + confidence across
  Tattva/Kunda/Trutine/Animodar/KP-RP/event-verification). Render a grounded summary + a confidence meter.
- Tier: enterprise (or a paid add-on). It's the most specialised mode.

## Tab gating summary

| tab | type | min tier |
|-----|------|----------|
| Natal | report_type=natal | basic |
| Maha-Kundali | report_type=maha_kundali | pro |
| Yearly | report_type=yearly | pro |
| Prashna | mode endpoint | pro |
| Chat | metered LLM (see CREDIT_LEDGER) | basic (small token grant) |
| Birth-Time Rectification | mode endpoint | enterprise |

The web reads `GET /v1/tiers` (extend it to also return report-type/mode entitlements) and the signed-in
user's tier to decide which tabs are live vs paywalled.
