# Nakshatra

Tiered Vedic-astrology product. Precision engine → deterministic findings → constrained LLM writer →
grounded, cited readings. Subscription tiers unlock more report types and sections; a metered LLM chat
answers follow-ups about the user's own chart.

- **`api/`** - FastAPI backend → Google Cloud Run.
- **`web/`** - Vite + React frontend → Firebase Hosting.
- **`docs/`** - design specs + the phased build plan.

**Start here:** [`CLAUDE.md`](./CLAUDE.md), then [`docs/BUILD_PLAN.md`](./docs/BUILD_PLAN.md).

## Run locally
```
# API (boots on mock engine + mock LLM if no secrets/engine present)
cd api && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env   # see docs/ARCHITECTURE.md ; place maha_jyotish_cloud_engine.py here (gitignored)
uvicorn app.main:app --reload

# web
cd web && npm install && cp .env.example .env   # add Firebase web config + VITE_API_BASE
npm run dev
```

## Deploy
```
# Prod API: use api/deploy/gcp_deploy.sh (sets APP_ENV=prod, CORS_ORIGINS, secrets). Bare command = dev only.
cd api && gcloud run deploy jyotish-api --source . --region asia-south1 --allow-unauthenticated
cd web && npm run build && firebase deploy --only hosting,firestore:rules   # firestore:rules ships the security rules
```

> Public repo. The proprietary engine, `.env`, and all secrets are gitignored and must never be committed.
