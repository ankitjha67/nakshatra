# CLAUDE.md, Nakshatra

Master context for working in this repo with Claude Code. Read this first, then `docs/`.

## What this is

**Nakshatra** is a tiered, subscription Vedic-astrology product. A precision ephemeris engine
computes a birth chart; a deterministic rules layer turns the raw chart into *findings*; a
tightly-constrained LLM phrases those findings into readable, **grounded** prose. Users sign in,
enter birth details, pick a report type, and get a reading whose every line traces back to a real
feature of their chart. Higher tiers unlock more report types and sections; an LLM **chat** lets
users ask follow-ups about their own chart, metered by a token credit ledger.

Live today: API on Google Cloud Run, web on Firebase Hosting, Firebase Auth, Firestore, Vertex/Gemini.

## Monorepo layout

```
/api    FastAPI backend (the engine wrapper + rules + renderer + tiers + storage). Deploys to Cloud Run.
/web    Vite + React frontend (tabs, forms, reading, chat, credits). Deploys to Firebase Hosting.
/docs   Design specs + the phased build plan. ARCHITECTURE, REPORT_TYPES, CREDIT_LEDGER, BUILD_PLAN.
```

Two independent deploys:
- **API** → `cd api && gcloud run deploy jyotish-api --source . --region asia-south1 --allow-unauthenticated`
- **web** → `cd web && npm run build && firebase deploy --only hosting,firestore:rules`
  (the `firestore:rules` target is **required** - it ships `web/firestore.rules`, the deny-by-default
  money/PII guard. Deploying `--only hosting` alone leaves the live DB on whatever ruleset it had.)

## The anti-slop architecture (the core idea, do not break this)

Four stages. The LLM is a **writer, not an interpreter**:

1. **Engine** (`api/engine_app.py` → `maha_jyotish_cloud_engine.py`) → raw chart JSON.
2. **Rules** (`api/app/rules.py`) → deterministic `Finding`s. *All interpretation happens here, in Python*,
   each finding carrying a `code`, `category`, `weight`, human `detail`, and `evidence` (the chart facts).
3. **Renderer** (`api/app/llm.py`) → the LLM is given only the findings + which sections to write, and
   may **only** phrase what the findings say. It must cite finding `code`s per section; any sentence
   citing nothing, or citing a code that wasn't supplied, is dropped post-generation.
4. **Reading** → `{summary, sections[], findings[], disclaimers[], meta}`.

Consequences that must be preserved when adding features:
- New astrology features become **new findings generators** in `rules.py` reading **real engine blocks**
  (never invent placements). A new user-facing area becomes a **section** in `llm.py`'s `SECTION_SPEC`.
- The renderer's `SYSTEM_PROMPT` forbids invented placements, generic horoscope filler, flattery,
  **fear/doom**, and absolute predictions. Keep it that way. Health stays *tendencies, not diagnosis*;
  numerology/remedies stay *traditional and optional*, never fatalistic or prescriptive.

## The engine (proprietary, NOT in this repo)

`maha_jyotish_cloud_engine.py` is the owner's proprietary engine. **It is gitignored and must never be
committed** (this repo is public). It lives locally in `api/` and is uploaded to Cloud Build at deploy
(it is intentionally *not* in `api/.gcloudignore`). Entry point:

```python
calculate_chart_json(name, dob, tob, lat, lon, tz_offset, city=None, country=None) -> dict
```
`dob` is `DD-MM-YYYY`, `tob` is `HH:MM` (24h), `tz_offset` is hours (e.g. 5.5). `engine_app.py` wraps it
and applies a **pysweph compatibility shim** (the maintained `pysweph` fork returns extra values from
`calc*/houses*`; the shim restores the original shapes). On import failure the app falls back to
`app/mock_engine.py` so the service still boots.

### Engine JSON shape (what rules may read)

Top-level keys: `engine, input, datetime, chart, cusps, panchang, moon_phase, hora, vargas,
ashtakavarga, bhava_chalit, arudha_padas, upagrahas, yogas, shadbala, kp_significators,
jaimini_karakas, vedic_aspects, planetary_wars, conjunctions, aspects_matrix, dasha_systems,
yogi_avayogi, bhrigu_bindu, indu_lagna, sade_sati, double_transit, numerology, sahams, danger_zones,
fixed_stars, eclipse_proximity, sarvatobhadra_chakra, kurma_chakra, financial_astrology,
planetary_ingress, birth_time_rectification`.

Key sub-shapes (verified against real output):
- `chart.asc` = `{deg, fmt, sign, nakshatra}`; `chart.mc`, `chart.asc_tropical`, `chart.mc_tropical`.
- `chart.planets[NAME]` = `{deg, fmt, sign(str), nakshatra, pada, status:{dignity, retrograde,
  combust, gandanta, mrityu_bhaga}}`. **No house field** - rules compute whole-sign:
  `house = ((planet_sign_idx - asc_sign_idx) % 12) + 1`.
- `chart.moon_nakshatra`, `chart.moon_pada`, `chart.nakshatra_lord`.
- `cusps.H1..H12` = `{deg, sign}` (KP/Placidus cusps; also numeric `"1".."12"`).
- `kp_significators.cusps.H1..H12` = `{deg, star, sub, ssl}` (cuspal sub-lords); `.planets[NAME]` same.
- `dasha_systems.vimshottari.current` = `{mahadasha, md_start, md_end, antardasha, ad_start, ad_end,
  all_antardashas}`; `.sequence` = list of `{planet, start, end, years}`; also `ashtottari, yogini,
  jaimini_chara` each `{current, sequence}`.
- `jaimini_karakas` = `{Atmakaraka, Amatyakaraka, Bhratrikaraka, Matrikaraka, Putrakaraka,
  Gnatikaraka, Darakaraka}`, each `{planet, sign, degree_in_sign}` (7-karaka scheme, no Rahu).
- `vargas` = `{D1, D2, D3, D4, D7, D9, D10, D12, D16, D20, D24, D27, D30, D40, D45, D60}`, each
  `{NAME:{deg, sign}, Lagna:{deg, sign}}`.
- `numerology` = `{psychic, destiny, name_compound, name_reduced, name_calculation, birth_day,
  compound_meaning}`.
- `sahams.sahams[NAME]` = `{deg, sign, topic}` (Punya, Vidya, Yashas, Sadhana, Vivaha, Pitri, Matri,
  Putra, Bhratri, Bandhu, Sneha, Dampati, Karma, Dhana, ...).
- `yogi_avayogi` = `{yogi_point, yogi_nakshatra, yogi_lord, avayogi_nakshatra, avayogi_lord,
  duplicate_yogi, interpretation}`. `bhrigu_bindu` = `{deg, sign, nakshatra}`. `indu_lagna` =
  `{sign, l9_lord, m9_lord, wealth_indicator}`.
- `ashtakavarga` = `{bav:{NAME:[12]}, sav:[12], total, strong_houses:[...], weak_houses:[...],
  average_per_house}`. `shadbala[NAME]` = `{..., rupas, required_rupas, is_strong}`.
- `fixed_stars` = list of `{star, planet, orb, star_lon, magnitude, nature, meaning}`.
- `double_transit` = `{active, houses:[...], saturn_sign, jupiter_sign, ...}`.
- `panchang` = `{tithi:{name,paksha,lord,...}, karana, yoga, vara:{name,lord}, nakshatra:{name,pada,lord}}`.
- `moon_phase` = `{phase_name, illumination_pct, waxing, waning, ...}`. `hora` = `{hora_lord, ...}`.
- `arudha_padas` = `{AL:{sign}, A2..A12:{sign}, UL:{sign}}` (AL = public image, UL = marriage).
- `danger_zones` = `{gandanta_planets:[{planet}], ...}`. `eclipse_proximity` = `{solar_eclipse_proximity,
  lunar_eclipse_proximity, ...}`.
- `birth_time_rectification` (only if `rectify_birth_time(...)` is called), used by the BTR mode.

Deliberately **not** surfaced as personal sections (by design): `financial_astrology`/Gann (market
timing, belongs in a trading product), `sarvatobhadra_chakra`, `kurma_chakra`, `planetary_ingress`
(mundane/transit). Don't add these to personal readings without a clear reason.

## Backend modules (`api/app/`)

- `__init__.py` - **version stamps**: `ENGINE_VERSION_FALLBACK`, `RULES_VERSION`, `RENDERER_VERSION`.
  These are part of every Firestore reading **cache key**. **RULE: bump the relevant stamp whenever you
  change rules, the renderer, `SECTION_SPEC`, or tier→section mapping, otherwise stale cached readings
  are served.** (Currently `rules-0.5`, `render-0.3`.)
- `config.py` - pydantic-settings; reads env (LLM provider, Vertex project/location/model, Firestore/
  Firebase project, default tier, CORS, admin key, cache flags).
- `models.py` - `BirthDetails` (+`chart_hash()`), `Finding{code,category,polarity,weight,title,detail,
  evidence}`, `ReadingSection{key,title,body,citations}`, `Meta`, `ReadingResponse`.
- `knowledge.py` - `SIGNS, SIGN_LORD, EXALT_SIGN, OWN_SIGNS, NAKSHATRA_LORD, DASHA_YEARS, KARAKA,
  HOUSE_MEANING, GRAHA_CATEGORY`, helpers.
- `engine.py` - engine boundary (reads `ENGINE_MODULE`/`ENGINE_CALLABLE`/`ENGINE_VERSION`; mock fallback).
- `rules.py` - **the anti-slop core**: defensive readers + finding generators + `derive_findings(chart)`.
  ~25 generators across categories: essence, mind, relationships, career, wealth, family, health,
  timing, fortune, spirit, strengths, kp, panchang, alerts, numbers, remedies.
- `llm.py` - `SECTION_SPEC` (16 sections, ordered), `SYSTEM_PROMPT`, `_group`, providers
  (`MockProvider` local, `VertexProvider`/`AnthropicProvider`/`OpenAIProvider`), `render_reading`
  (validates citations ⊆ finding codes, drops empties). `VertexProvider` sets `thinking_budget` and
  `max_output_tokens=max(.., 8192)` so the full report doesn't truncate.
- `billing.py` - `Tier`, `TIERS` (free/basic/pro/enterprise), `ALL_SECTIONS`, `MemoryStore` +
  `FirestoreStore`, `require_key`/`require_admin`/`enforce_quota`, `get_user`/`upsert_user`.
- `auth.py` - Firebase ID-token verification → `Principal`; `require_principal` accepts `Authorization:
  Bearer <idToken>` OR `X-API-Key`.
- `pipeline.py` - `get_chart` / `get_reading(birth, tier)`; caches by `chart_hash` + version stamps +
  unlocked sections.
- `main.py` - `GET /health`, `GET /v1/tiers`; `POST /v1/chart`, `POST /v1/reading`,
  `POST /v1/reading/async` + `GET /v1/reading/{job_id}`; admin + `POST /webhooks/payments`.

## Tiers (current)

| tier | ₹/mo | reading sections | daily | /min |
|------|------|------------------|-------|------|
| free | 0 | (chart only, no LLM) | 5 | 3 |
| basic | 299 | essence, mind, relationships, career, timing | 50 | 10 |
| pro | 999 | all 16 (full Maha-Kundali) + async | 500 | 30 |
| enterprise | 4999 | all 16 + API access | 10000 | 120 |

`DEFAULT_USER_TIER=pro` in the current deploy (so signed-in users see everything during build).
Flip + wire payments before launch.

## Deployment & config

- **API env vars** (set on the Cloud Run service): `ENGINE_MODULE=engine_app`,
  `ENGINE_CALLABLE=compute_chart`, `ENGINE_VERSION=maha-jyotish-7.0`, `LLM_PROVIDER=vertex`,
  `VERTEX_PROJECT=nakshatra-prod-2026`, `VERTEX_LOCATION=global` (gemini-2.5-pro is **not** served in
  asia-south1), `VERTEX_MODEL=gemini-2.5-pro`, `STORE_BACKEND=firestore`,
  `FIRESTORE_PROJECT=nakshatra-prod-2026`, `FIREBASE_PROJECT=nakshatra-prod-2026`,
  `DEFAULT_USER_TIER=pro`, `CACHE_READINGS=true`, `ADMIN_API_KEY=<secret>`. `gcloud run deploy --source .`
  preserves existing env across redeploys.
- **GCP**: project `nakshatra-prod-2026`, region `asia-south1`. Firestore Native DB in `asia-south1`.
  Runtime SA needs `roles/aiplatform.user` + `roles/datastore.user`; Cloud Build SA needs
  `roles/cloudbuild.builds.builder`. Firebase Auth: Email/Password on (Google sign-in optional).
- **web**: Firebase Hosting, project `nakshatra-prod-2026` → `https://nakshatra-prod-2026.web.app`
  (Auth authorizes `*.web.app` / `*.firebaseapp.com`). API `CORS_ORIGINS=*` today; tighten to the web
  origin before launch.

## Secrets & the public-repo rule

This repo is **public**. NEVER commit: `maha_jyotish_cloud_engine.py`, `.env`, service-account JSON,
`ADMIN_API_KEY`, payment keys. The Firebase **web API key** is *not* a secret (it ships in client code), it's fine in `web/`. Server secrets go in env / Secret Manager only.

## Guardrails for Claude Code (important)

- **Money & identity paths require human review.** Do not merge changes to the credit-debit logic,
  Firestore security rules, payment webhooks, or Firebase token verification without the owner reading
  the diff. See `docs/CREDIT_LEDGER.md`.
- **Token metering is server-side only.** The browser never reports tokens; the API reads Vertex usage
  and debits atomically. Never trust client-sent token counts. Always keep a per-turn `max_output_tokens`
  cap and a daily hard ceiling so a runaway chat can't burn unbounded spend.
- **Keep the LLM constrained to findings.** Don't let chat or any renderer answer free-floating
  astrology; ground every answer in the user's computed chart + findings.
- **Bump version stamps** in `app/__init__.py` on any rules/renderer/section/tier change (cache busting).
- **Never weaken** the `SYSTEM_PROMPT` anti-slop rules (no doom, no invented placements, health =
  tendencies not diagnosis, remedies optional). Don't commit secrets or the engine.
- Test new findings against real engine output, not guesses. Prefer small, reviewable diffs.

## Local dev

- API: `cd api && python -m venv .venv && . .venv/Scripts/activate && pip install -r requirements.txt`;
  copy the engine into `api/`; create `api/.env` (see `docs/ARCHITECTURE.md`); `uvicorn app.main:app --reload`.
  Without the engine it boots on the mock engine; without LLM creds it uses `MockProvider`.
- web: `cd web && npm install && npm run dev` → set the Firebase web config + `VITE_API_BASE` in `web/.env`.

Now read `docs/BUILD_PLAN.md` for the phased work, and `docs/REPORT_TYPES.md` + `docs/CREDIT_LEDGER.md`
for the two new subsystems.
