# docs/ARCHITECTURE.md — Request flow & environment

See `CLAUDE.md` for the full picture; this is the request flow + the env reference.

## Request flow

```
Browser (web/)                         API (api/, Cloud Run)
  sign in (Firebase) ───────────────▶  Authorization: Bearer <idToken>
  POST /v1/reading {birth, report_type}
                                        auth.require_principal  → uid, tier
                                        pipeline.get_reading(birth, tier)
                                          ├─ cache hit? (chart_hash + versions + sections) → return
                                          ├─ engine_app.compute_chart(birth) ──▶ chart JSON
                                          ├─ rules.derive_findings(chart)    ──▶ findings[]
                                          └─ llm.render_reading(findings, allowed_sections)
                                                 └─ Vertex/Gemini (writer; cites findings)
  ◀─────────────────────────────────  {summary, sections[], findings[], disclaimers[], meta}
  render sections + "Drawn from" footer
```

Chat (Phase 5) follows the same engine→findings path, then a grounded chat prompt, then a metered,
transactional token debit (see `CREDIT_LEDGER.md`).

## `api/.env` (local only — never commit)

```
APP_ENV=dev
LLM_PROVIDER=vertex            # or "mock" locally with no creds
VERTEX_PROJECT=nakshatra-prod-2026
VERTEX_LOCATION=global
VERTEX_MODEL=gemini-2.5-pro
ENGINE_MODULE=engine_app
ENGINE_CALLABLE=compute_chart
ENGINE_VERSION=maha-jyotish-7.0
STORE_BACKEND=firestore        # or "memory" locally
FIRESTORE_PROJECT=nakshatra-prod-2026
FIREBASE_PROJECT=nakshatra-prod-2026
DEFAULT_USER_TIER=pro
CACHE_READINGS=true
ADMIN_API_KEY=change-me
CORS_ORIGINS=*
# chat / credits (Phase 4–5)
CHAT_MAX_OUTPUT=800
DAILY_TOKEN_CEILING=200000
```
Local default-credentials for Vertex/Firestore: `gcloud auth application-default login`.

## `web/.env` (local only)

```
VITE_API_BASE=https://jyotish-api-1075458724715.asia-south1.run.app
VITE_FB_API_KEY=<firebase web api key>     # NOT secret; ships in client
VITE_FB_AUTH_DOMAIN=nakshatra-prod-2026.firebaseapp.com
VITE_FB_PROJECT_ID=nakshatra-prod-2026
```

## Deploy
- API: `cd api && gcloud run deploy jyotish-api --source . --region asia-south1 --allow-unauthenticated`
- web: `cd web && npm run build && firebase deploy --only hosting,firestore:rules` (rules target is required)
