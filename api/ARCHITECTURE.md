# Architecture & Plan

## 1. Goals

1. Run your existing Python astrology engine **independently in the cloud**.
2. Charge for it in **tiers**.
3. Layer an LLM that turns the JSON into readings **without AI slop**.

## 2. System overview

```
                         ┌─────────────────────────────────────────────┐
   Client / Nakshatra ──▶│  API (FastAPI on Cloud Run, container)       │
   site / mobile         │                                             │
                         │   /v1/chart   /v1/reading   /v1/reading/async│
                         └───────┬───────────────┬──────────────────────┘
                                 │               │
                 ┌───────────────▼──┐     ┌──────▼──────────┐
                 │ Engine (your     │     │ Cloud Tasks     │  (long readings)
                 │ Python) → JSON   │     │  → /internal/…  │
                 └───────────────┬──┘     └──────┬──────────┘
                                 ▼               ▼
                 ┌──────────────────┐     ┌─────────────────┐
                 │ Rules → findings │     │ LLM renderer    │──▶ Anthropic /
                 │ (deterministic)  │────▶│ (writer only)   │    OpenAI / Vertex
                 └──────────────────┘     └─────────────────┘
                                 │
                 ┌───────────────▼───────────────┐
                 │ Store: API keys, usage, cache, │  Firestore (or Postgres)
                 │ jobs                            │  Secret Manager for keys
                 └────────────────────────────────┘
```

The application is a single stateless container. It scales horizontally; all
state lives in the store. Nothing in the code is GCP-specific — the cloud
mappings in §9 are interchangeable.

## 3. The anti-slop strategy (the important part)

Generic "ask the model to interpret the chart" produces slop because the model
*invents* the substance. We invert that:

- **Stage 2 computes the interpretation.** `app/rules.py` emits `Finding`s —
  factual, jyotish-correct statements with explicit `evidence`
  (e.g. *"Jupiter exalted in Cancer, 5th house"*). This is testable Python.
- **Stage 3 only writes.** The renderer hands the model a fixed list of findings
  and the sections to write. The system prompt forbids any planet/house/yoga/
  dasha/date/prediction not in the findings, bans horoscope filler / flattery /
  fear / medical-legal-financial directives, and requires a `citations` array
  (finding codes) on every section.
- **Validation after generation.** Every citation is checked against the real
  finding codes; unsupported ones are dropped. A section with an empty body is
  dropped. So even a misbehaving model can't smuggle in a hallucination.
- **Determinism + low temperature + caching.** Same chart → same findings → same
  reading. Output is reproducible and auditable.

The included **mock provider** demonstrates the end state: it composes the
reading directly from findings (no model at all), and the output is already
coherent and fully grounded. Swapping in Claude/GPT/Gemini just makes the prose
nicer — it cannot make it less truthful.

## 4. Tiers & entitlements (`app/billing.py`)

| | Free | Basic | Pro | API/Business |
|---|---|---|---|---|
| Chart JSON | ✅ | ✅ | ✅ | ✅ |
| LLM reading | — | ✅ | ✅ | ✅ |
| Sections | — | essence, mind | all 6 | all 6 |
| Async readings | — | — | ✅ | ✅ |
| Programmatic/B2B | — | — | — | ✅ |
| Rate (req/min) | 3 | 10 | 30 | 120 |
| Daily cap | 5 | 50 | 500 | 10,000 |
| ₹ / month* | 0 | 299 | 999 | 4,999 |

\* Pricing is a starting point — set it from the cost model in §5.

## 5. Cost model (set prices with margin)

Per **reading** the variable costs are:

- **LLM tokens** — the dominant cost. A full six-section reading is roughly
  3–6k input + 1–3k output tokens. At commodity model rates that's on the order
  of a few ₹ to ~₹10 per *uncached* reading; a cheaper/flash model drops it to
  well under ₹1.
- **Compute** — Cloud Run bills per request-second; a chart + render is sub-second
  of CPU, fractions of a paisa.
- **Engine** — your CPU only.

**Caching is the biggest lever.** A natal chart never changes, so the reading is
cached by `chart_hash` (see `app/models.py`). Repeat views, re-loads, and the
same person across sessions cost **₹0**. Realistically a large share of traffic
is cache hits, so blended COGS per active user is low. Price tiers a healthy
multiple over uncached COGS and you have margin even on heavy users; the daily
cap protects you from abuse.

> Verify current token prices for your chosen model/region before finalising —
> they move. Keep `LLM_MAX_TOKENS` bounded (it already is) to cap worst-case spend.

## 6. Caching & determinism

Cache keys:

- chart: `chart:{chart_hash}:{engine_version}`
- reading: `read:{chart_hash}:{engine_version}:{rules_version}:{renderer_version}:{model}:{sections}`

Bump `ENGINE_VERSION`, `RULES_VERSION`, or `RENDERER_VERSION` (in `app/__init__.py`)
to invalidate cleanly when logic changes. In production back the cache with
Firestore (or Redis for hot data).

## 7. Store schema (for Firestore / Postgres)

`MemoryStore` ships for dev. To productionise, implement the same methods
(`get_key`, `create_key`, `set_tier`, `hit_rate`, `usage_today`, `record`,
`cache_get/put`, `job_put/get`) over:

**Firestore collections**
- `api_keys/{key}` → `{user_id, tier, disabled, created_at}`
- `usage/{key}_{yyyymmdd}` → `{calls, readings, tokens_in, tokens_out}` (atomic increments)
- `cache/{cache_key}` → reading/chart document
- `jobs/{job_id}` → `{status, result, error}`
- rate limiting → Redis (Memorystore) or a Firestore counter with TTL; a managed
  API gateway (see §9) can also enforce per-key quotas for you.

**Postgres tables**
- `api_keys(key pk, user_id, tier, disabled, created_at)`
- `usage(key, day, calls, readings, tokens_in, tokens_out, pk(key,day))`
- `readings_cache(cache_key pk, payload jsonb, created_at)`
- `jobs(job_id pk, status, result jsonb, error, updated_at)`

## 8. Async readings

Full readings can be slow on large models. `/v1/reading/async` returns a
`job_id`; clients poll `/v1/reading/{job_id}`. Locally it runs in a background
thread. In production set `CLOUD_TASKS_QUEUE` + `WORKER_BASE_URL` and the same
service receives the task at `/internal/run-reading` (guarded by `INTERNAL_TOKEN`).
This needs no separate worker image — Cloud Run handles both.

## 9. Cloud mappings (pick one)

| Concern | **GCP (recommended)** | AWS | Azure | Oracle |
|---|---|---|---|---|
| Run container | **Cloud Run** | App Runner / ECS Fargate | Container Apps | Container Instances |
| LLM | Vertex (Gemini) | Bedrock (Claude) | Azure OpenAI | OCI GenAI |
| App data | Firestore | DynamoDB | Cosmos DB | Autonomous DB |
| Secrets | Secret Manager | Secrets Manager | Key Vault | OCI Vault |
| Async queue | Cloud Tasks | SQS | Service Bus | Streaming/Queue |
| Tiered keys/quota (managed, optional) | API Gateway / Apigee | API Gateway usage plans | API Management products | API Gateway |

Why GCP Cloud Run: container-native (your engine's C deps & ephemeris files just
work), scale-to-zero (cheap while small), simple custom domains, first-class
Cloud Tasks + Secret Manager. If you'd rather have the platform meter tiers for
you, AWS API Gateway *usage plans* and Azure *APIM products* give per-key
quota/throttling out of the box — then this app just trusts the gateway's key.

## 10. Security

- API keys hashed at rest in production (store the hash, compare hashes); never
  log keys, birth data, or readings at INFO.
- Secrets only from Secret Manager / env — never committed. Rotate `ADMIN_API_KEY`
  and `INTERNAL_TOKEN`.
- Verify payment webhook signatures (Razorpay/Stripe) before trusting payloads
  (stubs in `app/main.py`).
- Birth data is personal; document retention, allow deletion, restrict CORS to
  your domains in prod (`CORS_ORIGINS`).
- TLS terminated by the platform; put Cloud Armor / WAF in front if public.

## 11. Roadmap / next steps

1. Connect your real engine (set the three `ENGINE_*` vars).
2. Choose the cloud + LLM; flip `LLM_PROVIDER`, add the key as a secret.
3. Implement `FirestoreStore` (or `PostgresStore`) — small, methods already defined.
4. Wire payments (Razorpay for India / Stripe) → webhook upgrades tier.
5. Add product depth as new **findings** (more yogas, transits/gochara,
   ashtakavarga, divisional charts) — prose quality rises automatically because
   the renderer just phrases new findings.
6. Optional: a thin frontend (your Nakshatra site) calling `/v1/reading`.
