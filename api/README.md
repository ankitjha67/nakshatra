# Jyotish Cloud

A tiered, cloud-hosted Vedic astrology API. You bring the calculation engine
(the Python that turns birth details into JSON); this wraps it into a billable
service whose interpretations are **grounded and slop-free** by design.

## The pipeline

```
Birth details
   │
   ▼
[1] Engine (YOUR code)        → chart JSON              app/engine.py  (+ app/mock_engine.py)
   │
   ▼
[2] Rules layer               → findings (with evidence) app/rules.py
   │   deterministic interpretation: dignities, yogas,
   │   lagna-lord placement, current dasha, retrogrades
   ▼
[3] LLM renderer              → prose, each line cited    app/llm.py
   │   the model may ONLY phrase the findings; it cannot
   │   invent placements/predictions. Citations validated.
   ▼
[4] Reading (JSON)            summary + sections + the findings behind them
```

**Why this kills AI slop:** the interpretation lives in stage 2 (Python you can
test and trust). Stage 3 is a *writer*, not an oracle, it gets a fixed list of
findings, must cite the finding code behind every section, and any sentence that
cites nothing real is discarded after generation. No vague horoscope filler, no
hallucinated planets, no fear-mongering, structurally, not by hoping.

## Run it locally (works with zero external services)

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

It boots with a **mock engine** and **mock LLM**, plus dev API keys
(`free_dev_key`, `basic_dev_key`, `pro_dev_key`, `ent_dev_key`).

```bash
# list tiers
curl localhost:8000/v1/tiers

# raw chart (any tier)
curl -X POST localhost:8000/v1/chart -H 'X-API-Key: free_dev_key' \
  -H 'content-type: application/json' \
  -d '{"date":"1992-08-14","time":"09:25","tz":"+05:30","lat":25.5941,"lon":85.1376}'

# full reading (Pro), note the cited sections in the response
curl -X POST localhost:8000/v1/reading -H 'X-API-Key: pro_dev_key' \
  -H 'content-type: application/json' \
  -d '{"date":"1992-08-14","time":"09:25","tz":"+05:30","lat":25.5941,"lon":85.1376}'

# provision a real key (admin)
curl -X POST localhost:8000/admin/keys -H 'X-Admin-Key: change-me-in-prod' \
  -H 'content-type: application/json' -d '{"user_id":"u_123","tier":"pro"}'
```

## Plug in your engine (the only required step)

Your engine just needs to be an importable callable that takes the birth dict
and returns a JSON-serialisable dict:

```python
# maha_jyotish/api.py
def compute_chart(birth: dict) -> dict:
    # birth = {"date","time","tz","lat","lon","ayanamsa","house_system", ...}
    return { "ascendant": {...}, "planets": [...], "dasha": {...}, "yogas": [...] }
```

Then set:

```
ENGINE_MODULE=maha_jyotish.api
ENGINE_CALLABLE=compute_chart
ENGINE_VERSION=maha-jyotish-7.0
```

The rules layer (`app/rules.py`) reads common field names defensively
(`planets`/`grahas`, `ascendant`/`lagna`, `dasha`/`vimshottari`). If your JSON
differs, adjust the small readers at the top of that file.

## Turn on a real LLM

Set `LLM_PROVIDER` to `anthropic`, `openai`, or `vertex` and provide the key.
The anti-slop prompt and citation validation apply to all of them.

## Tiers

| Tier | Reading | Sections | Async | API | ₹/mo* |
|------|---------|----------|-------|-----|-------|
| Free | - (chart JSON only) | - | - | - | 0 |
| Basic | yes | essence, mind | - | - | 299 |
| Pro | yes | all six | yes | - | 999 |
| API / Business | yes | all six | yes | yes | 4999 |

\* illustrative; see `ARCHITECTURE.md` for the cost model behind pricing.

## Deploy

GCP Cloud Run is the recommended target, see `deploy/gcp_deploy.sh`. AWS, Azure
and Oracle equivalents are in `deploy/CLOUD_NOTES.md`. A Terraform skeleton for
the GCP resources is in `deploy/terraform/`.

## Project layout

```
app/
  config.py      settings (env)
  models.py      schemas + birth-detail hashing (cache key)
  knowledge.py   classical Jyotish tables
  engine.py      engine boundary + plug-in loader
  mock_engine.py deterministic placeholder chart
  rules.py       findings (the interpretation)
  llm.py         prompts + providers + grounded renderer
  billing.py     tiers, store, auth, quota
  pipeline.py    orchestration + caching
  main.py        FastAPI routes
```
