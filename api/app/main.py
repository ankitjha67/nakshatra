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
import re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import Literal

_DATE_RE = r"\d{4}-\d{2}-\d{2}"
_TIME_RE = r"\d{2}:\d{2}"

from . import __version__, RULES_VERSION, RENDERER_VERSION
from .config import get_settings
from .models import BirthDetails, ChartResponse, ReadingResponse, JobResponse, Meta
from .billing import (
    Principal, Tier, TIERS, tier_catalog, report_type_catalog, get_store,
    require_admin, enforce_quota, enforce_global_breaker, _ct_eq, _WEAK_INTERNAL_TOKENS,
)
from .auth import require_principal
from .pipeline import get_chart, get_reading
from .engine import rectify_birth_time, engine_version
from .rules import derive_findings, derive_prashna, derive_btr
from .llm import chat_answer, render_reading, DISCLAIMERS
from .payments import handle_razorpay_webhook, PaymentError, TOPUP_PACKS

logging.basicConfig(level=get_settings().log_level)
log = logging.getLogger("api")

app = FastAPI(title="Jyotish Cloud", version=__version__,
              description="Tiered Vedic astrology API. Calculations are deterministic; "
                          "interpretation is computed in a rules layer; the LLM only renders prose.")

_origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins or ["*"],
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _prod_readiness():
    """Log loud warnings for risky prod config (dev defaults, open CORS, etc.)."""
    for msg in get_settings().startup_warnings():
        log.warning("PROD READINESS: %s", msg)


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/v1/tiers")
def tiers():
    packs = [{"inr": inr, "tokens": tok} for inr, tok in sorted(TOPUP_PACKS.items())]
    return {"tiers": tier_catalog(), "report_types": report_type_catalog(),
            "topup_packs": packs, "currency": "INR"}


@app.get("/v1/credits")
def credits_balance(p: Principal = Depends(require_principal)):
    """The signed-in user's chat-credit balance (read-only; runs lazy resets)."""
    return get_store().credit_balance(p.user_id, p.tier)


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
    enforce_global_breaker()
    resp = get_reading(birth, p.tier)
    get_store().record(p.key, resp.meta.tokens_in, resp.meta.tokens_out, reading=True)
    return resp


# --------------------------------------------------------------------------- #
# grounded chat (metered on the token credit ledger; see docs/CREDIT_LEDGER.md)
# --------------------------------------------------------------------------- #
class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(..., max_length=4000)


class ChatRequest(BaseModel):
    birth: BirthDetails                      # the cast chart this conversation is grounded in
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=16)
    chat_id: Optional[str] = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ChatResponse(BaseModel):
    answer: str
    tokens_used: int
    chat_id: str
    balance: dict                            # {grant, topup, available}


@app.post("/v1/chat", response_model=ChatResponse)
def chat(req: ChatRequest, p: Principal = Depends(require_principal)):
    s = get_settings()
    store = get_store()
    enforce_quota(p)                          # per-minute + daily call limits
    enforce_global_breaker()                  # platform-wide daily spend cap

    # --- credit pre-check (advisory; do NOT call the LLM if blocked) ---
    bal = store.credit_balance(p.user_id, p.tier)
    if bal["available"] <= 0:
        raise HTTPException(402, "You're out of chat credits — upgrade or add a top-up.")
    if bal["daily_used"] >= s.daily_token_ceiling:
        raise HTTPException(429, "Daily chat limit reached — please try again tomorrow.")

    # --- grounded answer: only from THIS chart's findings ---
    chart = get_chart(req.birth).chart
    findings = derive_findings(chart)
    history = [m.model_dump() for m in req.history]
    answer, _model, ti, to = chat_answer(findings, history, req.message, s.chat_max_output)
    cost = int(ti) + int(to)

    # --- atomic debit on the ledger (grant first, then topup; never below 0) ---
    msg_id = uuid.uuid4().hex
    bal2 = store.credit_debit(p.user_id, p.tier, cost, reason="chat turn", ref=msg_id)

    # --- persist the turn (best-effort; messages are not the money path) ---
    chat_id = req.chat_id or uuid.uuid4().hex
    try:
        store.chat_save_turn(p.user_id, chat_id, req.birth.chart_hash(),
                             req.message, answer, cost, msg_id)
    except Exception as exc:  # noqa: BLE001 — never log the message body (PII)
        log.warning("chat persistence failed (non-fatal) uid=%s chat_id=%s err=%s",
                    p.user_id, chat_id, type(exc).__name__)
    store.record(p.key, ti, to, reading=False)

    return ChatResponse(answer=answer, tokens_used=cost, chat_id=chat_id,
                        balance={"grant": bal2["grant"], "topup": bal2["topup"],
                                 "available": bal2["available"]})


# --------------------------------------------------------------------------- #
# Prashna / KP horary — a chart cast for the moment of asking (pro+)
# --------------------------------------------------------------------------- #
def _now_in_tz(tz: str) -> tuple[str, str]:
    """(YYYY-MM-DD, HH:MM) right now at a UTC offset like "+05:30" (UTC on parse fail)."""
    off = timedelta(0)
    m = re.fullmatch(r"\s*([+-])(\d{1,2}):?(\d{2})\s*", tz or "")
    if m:
        sign = 1 if m.group(1) == "+" else -1
        off = sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
    local = datetime.now(timezone.utc) + off
    return local.strftime("%Y-%m-%d"), local.strftime("%H:%M")


class PrashnaRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    tz: str = "+05:30"
    category: Optional[str] = None


@app.post("/v1/prashna", response_model=ReadingResponse)
def prashna(req: PrashnaRequest, p: Principal = Depends(require_principal)):
    if p.tier.key not in ("pro", "enterprise"):
        raise HTTPException(402, "Prashna (KP horary) is available on Pro and Enterprise.")
    enforce_quota(p)
    enforce_global_breaker()
    d, t = _now_in_tz(req.tz)                              # cast for the moment of asking
    birth = BirthDetails(date=d, time=t, tz=req.tz, lat=req.lat, lon=req.lon)
    cr = get_chart(birth)
    findings = derive_prashna(cr.chart, req.question, req.category)
    summary, sections, model_name, ti, to = render_reading(cr.chart, findings, {"prashna"})
    meta = Meta(engine_version=cr.meta.engine_version, rules_version=RULES_VERSION,
                renderer_version=RENDERER_VERSION, model=model_name, tier=p.tier.key,
                report_type="prashna", cache_hit=False, tokens_in=ti, tokens_out=to,
                chart_hash=birth.chart_hash())
    get_store().record(p.key, ti, to, reading=True)
    return ReadingResponse(summary=summary, sections=sections, findings=findings,
                           disclaimers=DISCLAIMERS, meta=meta)


# --------------------------------------------------------------------------- #
# Birth-Time Rectification — wraps the engine's rectify_birth_time (enterprise)
# --------------------------------------------------------------------------- #
class BtrEvent(BaseModel):
    date: str = Field(..., description="Event date, YYYY-MM-DD")
    type: str = Field(..., min_length=2, max_length=60, description="e.g. marriage, childbirth, accident")

    @field_validator("date")
    @classmethod
    def _date_ok(cls, v: str) -> str:
        if not re.fullmatch(_DATE_RE, v):
            raise ValueError("date must be YYYY-MM-DD")
        return v


class BtrRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=80)
    date: str = Field(..., description="Birth date, YYYY-MM-DD")
    time: str = Field(..., description="Approximate/known birth time, HH:MM")
    tz: str = Field("+05:30", max_length=40)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    gender: Literal["male", "female", "other"] = "other"
    sunrise_time: Optional[str] = Field(None, max_length=5)
    events: list[BtrEvent] = Field(default_factory=list, max_length=8)

    @field_validator("date")
    @classmethod
    def _date_ok(cls, v: str) -> str:
        if not re.fullmatch(_DATE_RE, v):
            raise ValueError("date must be YYYY-MM-DD")
        return v

    @field_validator("time")
    @classmethod
    def _time_ok(cls, v: str) -> str:
        if not re.fullmatch(_TIME_RE, v):
            raise ValueError("time must be HH:MM (24h)")
        return v

    @field_validator("sunrise_time")
    @classmethod
    def _sunrise_ok(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.fullmatch(_TIME_RE, v):
            raise ValueError("sunrise_time must be HH:MM (24h)")
        return v


class BtrResponse(ReadingResponse):
    rectification: dict                       # {recommended, candidates, methods, window, ...}


@app.post("/v1/btr", response_model=BtrResponse)
def btr(req: BtrRequest, p: Principal = Depends(require_principal)):
    if p.tier.key != "enterprise":
        raise HTTPException(402, "Birth-Time Rectification is an Enterprise mode.")
    if not req.events:
        raise HTTPException(422, "Provide at least one dated life event (3–5 recommended) to rectify against.")
    enforce_quota(p)
    enforce_global_breaker()
    payload = req.model_dump()
    payload["events"] = [e.model_dump() for e in req.events]
    rect = rectify_birth_time(payload)
    findings, norm = derive_btr(rect, payload)
    summary, sections, model_name, ti, to = render_reading(rect, findings, {"btr"})
    meta = Meta(engine_version=engine_version(), rules_version=RULES_VERSION,
                renderer_version=RENDERER_VERSION, model=model_name, tier=p.tier.key,
                report_type="btr", cache_hit=False, tokens_in=ti, tokens_out=to)
    get_store().record(p.key, ti, to, reading=True)
    return BtrResponse(summary=summary, sections=sections, findings=findings,
                       disclaimers=DISCLAIMERS, meta=meta, rectification=norm)


# --------------------------------------------------------------------------- #
# async readings
# --------------------------------------------------------------------------- #
def _run_job(job_id: str, birth: BirthDetails, tier_key: str, key: str):
    store = get_store()
    store.job_put(job_id, {"job_id": job_id, "status": "running", "owner": key})
    try:
        resp = get_reading(birth, TIERS[tier_key])
        store.record(key, resp.meta.tokens_in, resp.meta.tokens_out, reading=True)
        store.job_put(job_id, {"job_id": job_id, "status": "done", "owner": key, "result": resp.model_dump()})
    except Exception as exc:  # noqa: BLE001
        log.exception("job failed")
        store.job_put(job_id, {"job_id": job_id, "status": "error", "owner": key, "error": str(exc)})


@app.post("/v1/reading/async", response_model=JobResponse)
def reading_async(birth: BirthDetails, background: BackgroundTasks, p: Principal = Depends(require_principal)):
    if not p.tier.reading_allowed:
        raise HTTPException(402, "Readings not included in this tier.")
    if not p.tier.allow_async:
        raise HTTPException(402, f"Async readings require Pro or higher (current: {p.tier.label}).")
    enforce_quota(p)
    enforce_global_breaker()
    job_id = uuid.uuid4().hex
    get_store().job_put(job_id, {"job_id": job_id, "status": "queued", "owner": p.key})
    s = get_settings()
    if s.cloud_tasks_queue and s.worker_base_url:
        _enqueue_cloud_task(job_id, birth, p)              # production path
    else:
        background.add_task(_run_job, job_id, birth, p.tier.key, p.key)  # local path
    return JobResponse(job_id=job_id, status="queued")


@app.get("/v1/reading/{job_id}", response_model=JobResponse)
def reading_status(job_id: str, p: Principal = Depends(require_principal)):
    j = get_store().job_get(job_id)
    # 404 (not 403) on a foreign/unknown job so we don't leak that it exists.
    if not j or j.get("owner") != p.key:
        raise HTTPException(404, "Unknown job id")
    return JobResponse(**{k: v for k, v in j.items() if k != "owner"})


class _TaskPayload(BaseModel):
    job_id: str
    birth: BirthDetails
    tier: str
    key: str


@app.post("/internal/run-reading")
def internal_run(payload: _TaskPayload, x_internal_token: Optional[str] = Header(default=None)):
    s = get_settings()
    if s.internal_token in _WEAK_INTERNAL_TOKENS:
        raise HTTPException(503, "Internal worker disabled: set a strong INTERNAL_TOKEN")
    if not _ct_eq(x_internal_token, s.internal_token):
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
    """Provider-signed webhook → tier change (subscription) or top-up (one-time).

    MONEY PATH: the signature is verified over the RAW body and every entity is
    marked processed before crediting, so retries never double-credit. Client
    "I paid" claims are never trusted — only this signed callback mutates credits.
    """
    s = get_settings()
    raw = await request.body()
    if s.payments_provider != "razorpay":
        raise HTTPException(501, "No payments provider configured")
    if not s.razorpay_webhook_secret:
        raise HTTPException(503, "Payments webhook disabled: RAZORPAY_WEBHOOK_SECRET not configured")
    try:
        return handle_razorpay_webhook(
            raw, request.headers.get("X-Razorpay-Signature"),
            s.razorpay_webhook_secret, get_store(), TIERS,
        )
    except PaymentError as e:
        raise HTTPException(e.code, e.detail)
