"""FastAPI surface.

Public:   GET /health, GET /v1/tiers
Metered:  POST /v1/chart            (all tiers, rate-limited)
          POST /v1/reading          (tiers with LLM)
          POST /v1/reading/async    (tiers with async)  -> job id
          GET  /v1/reading/{job_id}
Admin:    POST /admin/keys          (X-Admin-Key) -> provision/upgrade a key
Webhook:  POST /webhooks/payments   (provider-signed) -> upgrade tier on payment
Internal: POST /internal/run-reading (Cloud Tasks callback; token-guarded)
"""
from __future__ import annotations

import logging
import secrets
import threading
import uuid
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import __version__
from .config import get_settings
from .models import BirthDetails, ChartResponse, ReadingResponse, JobResponse
from .billing import (
    Principal, Tier, TIERS, tier_catalog, get_store,
    require_admin, enforce_quota,
)
from .auth import require_principal
from .pipeline import get_chart, get_reading

logging.basicConfig(level=get_settings().log_level)
log = logging.getLogger("api")

app = FastAPI(title="Jyotish Cloud", version=__version__,
              description="Tiered Vedic astrology API. Calculations are deterministic; "
                          "interpretation is computed in a rules layer; the LLM only renders prose.")

_origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins or ["*"],
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/v1/tiers")
def tiers():
    return {"tiers": tier_catalog(), "currency": "INR"}


@app.post("/v1/chart", response_model=ChartResponse)
def chart(birth: BirthDetails, p: Principal = Depends(require_principal)):
    enforce_quota(p)
    resp = get_chart(birth)
    get_store().record(p.key, 0, 0, reading=False)
    return resp


@app.post("/v1/reading", response_model=ReadingResponse)
def reading(birth: BirthDetails, p: Principal = Depends(require_principal)):
    if not p.tier.reading_allowed:
        raise HTTPException(402, f"Readings are not included in the {p.tier.label} tier. Upgrade to Basic or higher.")
    enforce_quota(p)
    resp = get_reading(birth, p.tier)
    get_store().record(p.key, resp.meta.tokens_in, resp.meta.tokens_out, reading=True)
    return resp


# --------------------------------------------------------------------------- #
# async readings
# --------------------------------------------------------------------------- #
def _run_job(job_id: str, birth: BirthDetails, tier_key: str, key: str):
    store = get_store()
    store.job_put(job_id, {"job_id": job_id, "status": "running"})
    try:
        resp = get_reading(birth, TIERS[tier_key])
        store.record(key, resp.meta.tokens_in, resp.meta.tokens_out, reading=True)
        store.job_put(job_id, {"job_id": job_id, "status": "done", "result": resp.model_dump()})
    except Exception as exc:  # noqa: BLE001
        log.exception("job failed")
        store.job_put(job_id, {"job_id": job_id, "status": "error", "error": str(exc)})


@app.post("/v1/reading/async", response_model=JobResponse)
def reading_async(birth: BirthDetails, background: BackgroundTasks, p: Principal = Depends(require_principal)):
    if not p.tier.reading_allowed:
        raise HTTPException(402, "Readings not included in this tier.")
    if not p.tier.allow_async:
        raise HTTPException(402, f"Async readings require Pro or higher (current: {p.tier.label}).")
    enforce_quota(p)
    job_id = uuid.uuid4().hex
    get_store().job_put(job_id, {"job_id": job_id, "status": "queued"})
    s = get_settings()
    if s.cloud_tasks_queue and s.worker_base_url:
        _enqueue_cloud_task(job_id, birth, p)              # production path
    else:
        background.add_task(_run_job, job_id, birth, p.tier.key, p.key)  # local path
    return JobResponse(job_id=job_id, status="queued")


@app.get("/v1/reading/{job_id}", response_model=JobResponse)
def reading_status(job_id: str, p: Principal = Depends(require_principal)):
    j = get_store().job_get(job_id)
    if not j:
        raise HTTPException(404, "Unknown job id")
    return JobResponse(**j)


class _TaskPayload(BaseModel):
    job_id: str
    birth: BirthDetails
    tier: str
    key: str


@app.post("/internal/run-reading")
def internal_run(payload: _TaskPayload, x_internal_token: Optional[str] = Header(default=None)):
    if x_internal_token != get_settings().internal_token:
        raise HTTPException(403, "forbidden")
    _run_job(payload.job_id, payload.birth, payload.tier, payload.key)
    return {"status": "ok"}


def _enqueue_cloud_task(job_id: str, birth: BirthDetails, p: Principal):
    """Enqueue an HTTP task to Cloud Tasks that calls /internal/run-reading.

    Requires google-cloud-tasks. Kept import-local so the package runs without it.
    """
    from google.cloud import tasks_v2  # lazy
    s = get_settings()
    client = tasks_v2.CloudTasksClient()
    body = _TaskPayload(job_id=job_id, birth=birth, tier=p.tier.key, key=p.key).model_dump_json().encode()
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{s.worker_base_url}/internal/run-reading",
            "headers": {"Content-Type": "application/json", "X-Internal-Token": s.internal_token},
            "body": body,
        }
    }
    client.create_task(parent=s.cloud_tasks_queue, task=task)


# --------------------------------------------------------------------------- #
# admin + payments
# --------------------------------------------------------------------------- #
class KeyRequest(BaseModel):
    user_id: str
    tier: str = "basic"


@app.post("/admin/keys")
def create_key(req: KeyRequest, _: None = Depends(require_admin)):
    if req.tier not in TIERS:
        raise HTTPException(400, f"Unknown tier; choose from {list(TIERS)}")
    api_key = "jk_" + secrets.token_urlsafe(24)
    get_store().create_key(api_key, req.user_id, req.tier)
    return {"api_key": api_key, "user_id": req.user_id, "tier": req.tier}


class UserTierRequest(BaseModel):
    uid: str
    tier: str


@app.post("/admin/users/tier")
def set_user_tier(req: UserTierRequest, _: None = Depends(require_admin)):
    """Set a Firebase user's tier by uid (payment webhook / ops use this)."""
    if req.tier not in TIERS:
        raise HTTPException(400, f"Unknown tier; choose from {list(TIERS)}")
    store = get_store()
    store.upsert_user(req.uid, None)
    store.set_tier(req.uid, req.tier)
    return {"uid": req.uid, "tier": req.tier}


@app.post("/webhooks/payments")
async def payments_webhook(request: Request):
    """Verify the provider signature, then upgrade the payer's tier.

    Signature verification is provider-specific (Razorpay/Stripe); the handler
    below sketches the flow. Wire your real verification before going live.
    """
    s = get_settings()
    raw = await request.body()
    if s.payments_provider == "razorpay":
        # import razorpay; razorpay.Utility().verify_webhook_signature(raw.decode(),
        #   request.headers.get("X-Razorpay-Signature"), s.razorpay_webhook_secret)
        pass
    elif s.payments_provider == "stripe":
        # import stripe; stripe.Webhook.construct_event(raw,
        #   request.headers.get("Stripe-Signature"), s.stripe_webhook_secret)
        pass
    else:
        raise HTTPException(501, "No payments provider configured")
    payload = await request.json()
    user_id = (payload.get("notes") or {}).get("user_id") or payload.get("client_reference_id")
    tier = (payload.get("notes") or {}).get("tier") or "pro"
    if user_id and tier in TIERS:
        get_store().set_tier(user_id, tier)
        return {"status": "upgraded", "user_id": user_id, "tier": tier}
    return {"status": "ignored"}
