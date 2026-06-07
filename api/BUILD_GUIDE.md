# Nakshatra — Build Guide (step by step)

A guided path from nothing to a working pipeline on your own domain, then to a
paid product. Follow the phases in order. **Phases 0–4 are the MVP** ("website on
a domain + GCP + DB + the pipeline works"). Phases 5–6 are the "then we add
payments / API / gateways" batch.

---

## 0. The architecture (what we're building)

```
Browser ── Nakshatra site (Firebase Hosting, your domain + auto-SSL + CDN)
   │  sign in with Firebase Auth → ID token
   ▼
api.yourdomain  ──  FastAPI on Cloud Run (container)
   │   1. verify Firebase ID token → uid
   │   2. resolve user + tier from Firestore
   │   3. YOUR engine (monolith) → chart JSON
   │   4. rules layer → findings (deterministic interpretation)
   │   5. Vertex AI (Gemini) renders the reading / answers chat — WRITER ONLY
   │   6. store chart + reading + messages in Firestore; meter usage
   ▼
Firestore (users, charts, readings, chats, usage/credits)
Secret Manager (keys)      Vertex AI (LLM)      Razorpay (payments, later)
```

**Recommended stack (one GCP project throughout):**

| Layer | Service |
|---|---|
| Static site | Firebase Hosting |
| Auth | Firebase Authentication (Google + email link) |
| API/compute | Cloud Run (the `jyotish-cloud` FastAPI app) |
| LLM | Vertex AI Gemini (alt: Anthropic Claude via API key) |
| Database | Firestore (Native mode) |
| Secrets | Secret Manager |
| Async (optional) | Cloud Tasks |
| Payments (later) | Razorpay |

Why these: Firebase Auth gives you per-user identity (required to meter chat)
with almost no code; Firestore pairs with it and scales to zero; Cloud Run runs
your monolith and its native deps without the packaging pain of Lambda; Vertex
uses IAM (no API key to manage) and keeps data in-cloud.

---

## 1. Firestore data model

```
users/{uid}
  { email, displayName, tier: "free|basic|pro", createdAt }

users/{uid}/charts/{chartHash}
  { birth: {...}, chart: {...}, findings: [...], createdAt }     # cache per user

users/{uid}/readings/{readingId}
  { chartHash, summary, sections: [...], model, createdAt }

users/{uid}/chats/{sessionId}
  { chartHash, title, createdAt }
users/{uid}/chats/{sessionId}/messages/{msgId}
  { role: "user|assistant", content, tokensIn, tokensOut, createdAt }

usage/{uid}_{YYYYMM}
  { readings, chatMessages, tokensIn, tokensOut }               # monthly meter

credits/{uid}
  { topupMessages: 0, usedThisMonth: 0, monthKey: "2026-06" }   # purchased balance
```

**Remaining chat credits** = `allowance(tier) - usage.chatMessages_this_month + credits.topupMessages`.
The plan allowance resets monthly; top-ups (Phase 6) add to `topupMessages`.

---

## 2. Phase 0 — Foundations

**Goal:** project, services, domain, and an importable engine.

```bash
# CLIs
curl https://sdk.cloud.google.com | bash && exec -l $SHELL      # gcloud
npm i -g firebase-tools                                          # firebase
gcloud auth login && firebase login

# Project (use your own id)
gcloud projects create nakshatra-prod --name="Nakshatra"
gcloud config set project nakshatra-prod
# link billing in console: console.cloud.google.com/billing

# APIs
gcloud services enable run.googleapis.com firestore.googleapis.com \
  secretmanager.googleapis.com aiplatform.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com \
  identitytoolkit.googleapis.com cloudtasks.googleapis.com

# Firestore (Native), Mumbai
gcloud firestore databases create --location=asia-south1

# Firebase: add Firebase to this GCP project (console → Add project → pick
# nakshatra-prod), then enable Auth providers:
#   Authentication → Sign-in method → enable Google + Email link.
```

**Domain.** Register via Cloud Domains (in-project, simplest) or any registrar:

```bash
gcloud domains registrations register YOURDOMAIN.com   # or use an existing one
```
Plan: root `yourdomain.com` → the site; `api.yourdomain.com` → Cloud Run.

**Make your monolith importable (the only required code change).** Target shape:

```python
# engine_app.py  (or your existing file)
def compute_chart(birth: dict) -> dict:
    # birth = {"date","time","tz","lat","lon","ayanamsa","house_system", ...}
    ...
    return result_dict          # whatever your engine emits (must be JSON-serialisable)
```
If your code is a script (reads args/stdin, prints JSON), see **Appendix A**.

**Done when:** `python -c "import engine_app, json; print(json.dumps(engine_app.compute_chart({...})))"`
prints your JSON locally.

---

## 3. Phase 1 — Backend reading slice on Cloud Run

**Goal:** `curl api.../v1/reading` returns a grounded reading from YOUR engine.

1. Use the `jyotish-cloud` project from this chat. Copy your engine file into it
   (and add its deps to `requirements.txt`, e.g. `pyswisseph`; if it needs
   ephemeris data files, `COPY` them in the Dockerfile and set the path env).
2. Configure (`.env` for local, env vars for Cloud Run):
   ```
   ENGINE_MODULE=engine_app
   ENGINE_CALLABLE=compute_chart
   ENGINE_VERSION=maha-jyotish-7.0
   LLM_PROVIDER=vertex
   VERTEX_PROJECT=nakshatra-prod
   VERTEX_LOCATION=asia-south1
   STORE_BACKEND=memory        # temporary; switch to firestore in Phase 2
   ```
3. Adjust the readers at the top of `app/rules.py` if your JSON field names
   differ from the defaults (planets/grahas, ascendant/lagna, dasha/vimshottari).
4. Local smoke test:
   ```bash
   pip install -r requirements.txt google-genai
   uvicorn app.main:app --reload
   curl -X POST localhost:8000/v1/reading -H 'X-API-Key: pro_dev_key' \
     -H 'content-type: application/json' \
     -d '{"date":"1992-08-14","time":"09:25","tz":"+05:30","lat":25.5941,"lon":85.1376}'
   ```
5. Deploy (edit vars in `deploy/gcp_deploy.sh`, then run it). Grant the Cloud Run
   service account: `roles/aiplatform.user`, `roles/secretmanager.secretAccessor`
   (and `roles/datastore.user` for Phase 2).

**Done when:** the deployed URL returns a reading whose `sections` are cited and
whose content comes from your engine via Vertex.

---

## 4. Phase 2 — Auth + Firestore

**Goal:** logged-in users; readings + usage persisted per user.

**a) Verify Firebase ID tokens** (add to the backend):

```python
# app/auth_firebase.py
import firebase_admin
from firebase_admin import auth as fb_auth
from fastapi import Header, HTTPException

firebase_admin.initialize_app()       # uses Cloud Run's service account (ADC)

async def current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        return fb_auth.verify_id_token(authorization.split(" ", 1)[1])  # {uid,email,...}
    except Exception:
        raise HTTPException(401, "Invalid token")
```
Use `Depends(current_user)` on `/v1/reading` and `/v1/chat` instead of the API
key for the web app. (Keep the API-key path for the public API in Phase 6.)
Add `firebase-admin` to `requirements.txt`.

**b) Implement `FirestoreStore`** mirroring `MemoryStore`'s methods (the
interface is already defined in `app/billing.py`), backed by the collections in
§1. On first request for a uid, create the `users/{uid}` doc with `tier="free"`.
Then set `STORE_BACKEND=firestore`. *(Ask me and I'll generate this file.)*

**Done when:** signing in and requesting a reading writes
`users/{uid}/readings/...` and bumps `usage/{uid}_{YYYYMM}`.

---

## 5. Phase 3 — Website on your domain

**Goal:** the Nakshatra site, with login + birth form, live on your domain.

1. Start from `nakshatra-orrery.html`. Add the Firebase web SDK and:
   - a **Sign in with Google** button,
   - a **birth-details form** (date, time, place→lat/lon, tz),
   - a **reading view** that renders `summary`, `sections`, and the `findings`
     ("based on: …") for trust.
2. Call the API with the ID token:
   ```js
   const API = "https://api.yourdomain.com";
   const token = await firebase.auth().currentUser.getIdToken();
   const res = await fetch(`${API}/v1/reading`, {
     method: "POST",
     headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
     body: JSON.stringify(birth),
   });
   const reading = await res.json();
   ```
   (For place → coordinates, use a geocoding lookup or a city dropdown; keep it
   simple for MVP.)
3. Deploy + domain:
   ```bash
   firebase init hosting          # public dir = where your index.html lives
   firebase deploy --only hosting,firestore:rules   # rules target ships web/firestore.rules
   # Hosting → Add custom domain → yourdomain.com  (auto-SSL)
   # Point the API subdomain at Cloud Run:
   gcloud run domain-mappings create --service jyotish-api \
     --domain api.yourdomain.com --region asia-south1
   ```
   Set `CORS_ORIGINS=https://yourdomain.com` on the Cloud Run service.

**Done when:** visit your domain → sign in → submit birth details → see your
reading rendered.

---

## 6. Phase 4 — Chat + credits

**Goal:** grounded follow-up Q&A, metered per user.

**Backend — `/v1/chat`:**

```python
# sketch — grounding keeps it anti-slop; credits gate usage
@app.post("/v1/chat")
def chat(req: ChatRequest, user = Depends(current_user)):
    uid = user["uid"]
    if remaining_credits(uid) <= 0:
        raise HTTPException(402, "Out of chat credits — upgrade or top up")
    grounding = load_grounding(uid, req.chart_hash)   # chart + findings + reading text
    reply, ti, to = llm_chat(grounding, req.history, req.message)
    debit_credit(uid)                                 # +1 chatMessages this month
    store_message(uid, req.session_id, req.message, reply, ti, to)
    return {"reply": reply, "remaining": remaining_credits(uid)}
```

Chat **system prompt** (same anti-slop spirit as the renderer):
> You are a Jyotish guide answering questions about THIS person's chart. Use only
> the chart facts and findings provided. If a question isn't supported by the
> chart, say so — never invent placements, dates, or predictions. No medical,
> legal, or financial directives. Reference the relevant placement when you can.

The grounding (chart + findings + reading) is injected every turn, so answers
stay tied to the real chart. Bound `LLM_MAX_TOKENS` to cap per-message cost.

**Credits/tiers for MVP** (no purchasing yet — fixed allowances):

| Tier | Reading sections | Chat messages / month |
|---|---|---|
| Free | summary + 1 section | 5 (trial) |
| Basic | 2 sections | 100 |
| Pro | all 6 + dasha timing | 1000 |

Set a user's tier manually in Firestore for now; real upgrades arrive in Phase 6.

**Frontend:** a chat panel under the reading; show "X messages left"; when low,
show **Upgrade / Top up** (wired to payments in Phase 6).

**Optional polish:** stream the reply (Vertex streaming → SSE from Cloud Run →
append tokens in the UI).

**Done when:** ask follow-ups → grounded answers → balance decrements → hitting 0
prompts upgrade.

> **This is the MVP.** The pipeline works on your domain. Stop here, use it,
> watch real token usage, then continue.

---

## 7. Phase 5 — Harden (still pre-payments)

- **Firestore security rules:** users can read/write only their own docs; all
  writes that matter go through the backend (Admin SDK bypasses rules).
- **CORS** locked to `https://yourdomain.com`.
- **Rate limits** per uid (the quota logic exists; key it by uid, back it with
  Firestore or Redis/Memorystore).
- **Logging** without PII — never log birth data, tokens, or reading text at INFO.
- **"Delete my data"** endpoint (privacy; birth data is personal).
- **Budget alert** + `--max-instances` on Cloud Run; keep `LLM_MAX_TOKENS` bounded.

---

## 8. Phase 6+ — Payments, public API, gateway, more features

**Payments (Razorpay):**
- Subscriptions for tiers + one-time **top-up packs** (e.g., +500 messages).
- Checkout on the site → Razorpay → **webhook** to `/webhooks/payments`
  (signature-verified, stub already in `app/main.py`) → set `tier` /
  increment `credits.topupMessages` in Firestore.

**Public API (B2B):** the API-key path in `app/billing.py` is already built —
issue `jk_…` keys per the tier system, document the endpoints, sell programmatic
access. Optionally front it with **API Gateway / Apigee** for managed quotas.

**More features → more sections/endpoints:** map each capability in your monolith
to a finding/section. Natural additions: transits (gochara), dasha forecast,
divisional charts, **Guna Milan** compatibility (two charts in → a match reading),
muhurta. Because the renderer only phrases findings, new features improve the
reading automatically once you emit findings for them.

---

## Appendix A — wrapping a monolithic engine

**Pattern 1 — import & call (best).** Refactor the entry point into a function
that returns a dict; point `ENGINE_MODULE`/`ENGINE_CALLABLE` at it. No behaviour
change, just expose a callable.

**Pattern 2 — keep the script, wrap it.** If it does
`if __name__ == "__main__": main()` and prints JSON, add a thin module:
```python
# engine_app.py
import io, json, contextlib
import your_monolith                     # the script, imported as a module
def compute_chart(birth: dict) -> dict:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        your_monolith.run(birth)          # or call its main with params
    return json.loads(buf.getvalue())
```

**Pattern 3 — subprocess (last resort, no refactor).**
```python
import subprocess, json
def compute_chart(birth: dict) -> dict:
    p = subprocess.run(["python", "monolith.py"], input=json.dumps(birth),
                       capture_output=True, text=True, check=True)
    return json.loads(p.stdout)
```
Prefer 1 or 2 (in-process is faster and cheaper than spawning).

**Heavy deps:** if it uses Swiss Ephemeris, add `pyswisseph` to requirements,
`COPY` the `.se1` ephemeris files into the image, and set the ephemeris path your
engine expects. Build once; Cloud Run reuses the image.

---

## Appendix B — cost levers (so chat stays cheap)

- **Cache** charts and readings by `chart_hash` (already in the app) — repeat
  views cost ₹0; a natal chart never changes.
- **Bound `LLM_MAX_TOKENS`** — caps worst-case per message.
- **Cheaper model for chat than for the headline reading** if needed (set per
  call).
- **Monthly allowances + paid top-ups** priced a healthy multiple over token
  cost. Measure real token usage during the MVP before fixing prices.

---

## Appendix C — environment reference

See `.env.example` in the project. Key ones for this build:
`ENGINE_MODULE`, `ENGINE_CALLABLE`, `ENGINE_VERSION`, `LLM_PROVIDER=vertex`,
`VERTEX_PROJECT`, `VERTEX_LOCATION`, `STORE_BACKEND=firestore`,
`FIRESTORE_PROJECT`, `CORS_ORIGINS`, `LLM_MAX_TOKENS`, `ADMIN_API_KEY`.
