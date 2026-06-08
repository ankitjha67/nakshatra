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
    enforce_quota, enforce_global_breaker, _ct_eq, _WEAK_INTERNAL_TOKENS,
)
from .auth import require_principal, delete_firebase_user, require_admin
from .pipeline import get_chart, get_reading
from .anchor import derive_anchor
from .gating import filter_chart_for_features, filter_findings
from .codes import generate_plaintext, hash_code
from .engine import rectify_birth_time, engine_version
from .rules import derive_findings, derive_prashna, derive_btr
from .llm import chat_answer, render_reading, DISCLAIMERS
from .payments import (handle_razorpay_webhook, PaymentError, TOPUP_PACKS,
                       create_razorpay_order, create_razorpay_subscription,
                       cancel_razorpay_subscription, keys_configured)
from .mock_razorpay import checkout_event as _mock_checkout_event, refund_event as _mock_refund_event
from . import pricing


def _payments_secret() -> str:
    """Webhook signing secret; falls back to a dev-only value for the mock gateway."""
    s = get_settings()
    if s.razorpay_webhook_secret:
        return s.razorpay_webhook_secret
    if s.is_prod:
        raise HTTPException(503, "Payments not configured")
    return "mock_secret"

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
    # Financial guardrail: every paid tier's grant must be profit-gated (>=50% margin
    # at full utilization). A drift here means a tier could run at a loss.
    for k, t in TIERS.items():
        if t.monthly_tokens and not pricing.tier_is_gated(t.price_inr_month, t.monthly_tokens):
            log.warning("PRICING GATE: tier '%s' grant %d exceeds its 50%%-margin gate (%d), "
                        "it can run at a loss at full utilization.",
                        k, t.monthly_tokens, pricing.gated_grant_tokens(t.price_inr_month))


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


@app.get("/v1/me")
def me(p: Principal = Depends(require_principal)):
    """The signed-in user's profile + entitlements + balance (frontend reads its real tier here)."""
    store = get_store()
    user = store.get_user(p.user_id) or {}
    return {"user_id": p.user_id, "tier": p.tier.key,
            "sections": sorted(p.tier.sections), "features": sorted(p.tier.features),
            "discount_pct": int(user.get("discount_pct") or 0),
            "birth_lock": user.get("birth_lock"),
            "birth_change_pending": bool(store.user_open_change_request(p.user_id)),
            "has_subscription": bool(user.get("subscription_id")),
            "balance": store.credit_balance(p.user_id, p.tier)}


@app.get("/v1/me/export")
def me_export(p: Principal = Depends(require_principal)):
    """GDPR data portability, the user's own stored data (profile, ledger, chats)."""
    return get_store().export_user(p.user_id)


@app.delete("/v1/me")
def me_delete(p: Principal = Depends(require_principal)):
    """GDPR right to erasure, delete the user's record, ledger, chats, API keys,
    and (best-effort) the Firebase Auth identity."""
    res = get_store().delete_user(p.user_id)
    res["firebase_identity"] = delete_firebase_user(p.user_id)
    return {"status": "deleted", **res}


def enforce_birth_lock(uid: str, b) -> None:
    """Lock ONE native (person = date + place) per account. First birth-based call
    saves it; afterwards a different person (different DOB/place) is rejected (409).
    Time-only changes (BTR / typo fix on the same person) are still allowed. This
    closes the loophole where one subscription reads unlimited different people."""
    if not get_settings().birth_lock_enabled:
        return
    store = get_store()
    pk = f"{b.date}|{float(b.lat):.2f}|{float(b.lon):.2f}"
    lock = store.get_birth_lock(uid)
    if lock:
        if lock.get("person_key") != pk:
            raise HTTPException(409, "Your birth details are locked to this account. "
                                     "Contact support to change the saved birth details.")
        return
    store.set_birth_lock(uid, {
        "person_key": pk, "name": getattr(b, "name", None), "date": b.date,
        "time": b.time, "tz": b.tz, "lat": b.lat, "lon": b.lon,
        "place": getattr(b, "place", None)})


@app.post("/v1/chart", response_model=ChartResponse)
def chart(birth: BirthDetails, p: Principal = Depends(require_principal)):
    enforce_quota(p)
    enforce_birth_lock(p.user_id, birth)
    resp = get_chart(birth)
    get_store().record(p.key, 0, 0, reading=False)
    # tier feature-gate: strip divisional/full-table blocks the tier doesn't include
    resp.chart = filter_chart_for_features(resp.chart, p.tier.features)
    return resp


@app.post("/v1/anchor")
def anchor(birth: BirthDetails, p: Principal = Depends(require_principal)):
    """Maha-Jyotish anchor verification block (Tropical vs Sidereal Asc/Moon,
    Nakshatra lock, danger flags). Cheap, engine-only, no LLM, no credit debit,
    shown for the user to verify against an external panchang before the reading."""
    if "anchor" not in p.tier.features:
        raise HTTPException(402, "The anchor block is not included in your plan.")
    enforce_quota(p)
    enforce_birth_lock(p.user_id, birth)
    resp = get_chart(birth)
    get_store().record(p.key, 0, 0, reading=False)
    return {"anchor": derive_anchor(resp.chart, birth), "meta": resp.meta}


@app.post("/v1/reading", response_model=ReadingResponse)
def reading(birth: BirthDetails, p: Principal = Depends(require_principal)):
    if not p.tier.reading_allowed:
        raise HTTPException(402, f"Readings are not included in the {p.tier.label} tier. Upgrade to Basic or higher.")
    enforce_quota(p)
    enforce_global_breaker()
    enforce_birth_lock(p.user_id, birth)
    store = get_store()
    # readings draw on the same metered AI allowance as chat (the cost gate)
    if p.tier.monthly_tokens and store.credit_balance(p.user_id, p.tier)["available"] <= 0:
        raise HTTPException(402, "You're out of credits for this cycle, upgrade or add a top-up.")
    resp = get_reading(birth, p.tier)
    if "varshphal" not in p.tier.features:        # Tajik annual block is Pro+
        resp.varshphal = None
    cost = int(resp.meta.tokens_in) + int(resp.meta.tokens_out)
    if cost:                                  # cache hits cost 0 tokens -> free
        store.credit_debit(p.user_id, p.tier, cost, reason="reading", ref=resp.meta.chart_hash)
    store.record(p.key, resp.meta.tokens_in, resp.meta.tokens_out, reading=True)
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
        raise HTTPException(402, "You're out of chat credits, upgrade or add a top-up.")
    if bal["daily_used"] >= s.daily_token_ceiling:
        raise HTTPException(429, "Daily chat limit reached, please try again tomorrow.")

    # --- grounded answer: only from THIS chart's findings, AND only the ones the
    # user's tier unlocks. Context minimization is the core jailbreak defense, the
    # model can't reveal a higher tier (or anything else) that isn't in its context.
    enforce_birth_lock(p.user_id, req.birth)
    chart = get_chart(req.birth).chart
    findings = filter_findings(derive_findings(chart), p.tier.sections)
    # Server-authoritative history: load prior turns from the store by chat_id; the
    # client-supplied req.history is IGNORED for grounding so a crafted client can't
    # inject fake turns. (Stateless if persistence is off or it's a new conversation.)
    chat_id = req.chat_id or uuid.uuid4().hex
    history = (store.chat_get_turns(p.user_id, chat_id, limit=16)
               if (req.chat_id and s.persist_chat) else [])
    answer, _model, ti, to = chat_answer(findings, history, req.message, s.chat_max_output)
    cost = int(ti) + int(to)

    # --- atomic debit on the ledger (grant first, then topup; never below 0) ---
    msg_id = uuid.uuid4().hex
    bal2 = store.credit_debit(p.user_id, p.tier, cost, reason="chat turn", ref=msg_id)

    # --- persist the turn (best-effort, opt-out via PERSIST_CHAT; not the money path) ---
    if s.persist_chat:
        try:
            store.chat_save_turn(p.user_id, chat_id, req.birth.chart_hash(),
                                 req.message, answer, cost, msg_id)
        except Exception as exc:  # noqa: BLE001, never log the message body (PII)
            log.warning("chat persistence failed (non-fatal) uid=%s chat_id=%s err=%s",
                        p.user_id, chat_id, type(exc).__name__)
    store.record(p.key, ti, to, reading=False)

    return ChatResponse(answer=answer, tokens_used=cost, chat_id=chat_id,
                        balance={"grant": bal2["grant"], "topup": bal2["topup"],
                                 "available": bal2["available"]})


# --------------------------------------------------------------------------- #
# Prashna / KP horary, a chart cast for the moment of asking (pro+)
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
# Birth-Time Rectification, wraps the engine's rectify_birth_time (enterprise)
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
        raise HTTPException(422, "Provide at least one dated life event (3-5 recommended) to rectify against.")
    enforce_quota(p)
    enforce_global_breaker()
    enforce_birth_lock(p.user_id, req)   # BTR refines time on the SAME person (date+place must match)
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
    source: Optional[str] = Field(None, max_length=32, description="e.g. 'payment', 'beta', 'admin'")


@app.post("/admin/users/tier")
def set_user_tier(req: UserTierRequest, _: None = Depends(require_admin)):
    """Set a Firebase user's tier by uid (payment webhook / ops use this)."""
    if req.tier not in TIERS:
        raise HTTPException(400, f"Unknown tier; choose from {list(TIERS)}")
    store = get_store()
    store.upsert_user(req.uid, None)
    store.set_tier(req.uid, req.tier, source=req.source)
    return {"uid": req.uid, "tier": req.tier, "source": req.source}


# --------------------------------------------------------------------------- #
# beta cohort: grant a few users elevated access for feedback, tagged so they
# can be revoked en masse before switching to live Razorpay billing.
# --------------------------------------------------------------------------- #
class BetaGrantRequest(BaseModel):
    uid: str
    tier: str = "enterprise"


@app.post("/admin/beta/grant")
def beta_grant(req: BetaGrantRequest, _: None = Depends(require_admin)):
    """Grant a user elevated access tagged tier_source='beta' (reversible later)."""
    if req.tier not in TIERS:
        raise HTTPException(400, f"Unknown tier; choose from {list(TIERS)}")
    store = get_store()
    store.upsert_user(req.uid, None)
    store.set_tier(req.uid, req.tier, source="beta")
    return {"uid": req.uid, "tier": req.tier, "source": "beta"}


@app.get("/admin/beta")
def beta_list(_: None = Depends(require_admin)):
    """List the current beta-tagged users (for review before revoking)."""
    users = [u for u in get_store().list_users() if (u or {}).get("tier_source") == "beta"]
    return {"count": len(users),
            "users": [{"uid": u.get("uid") or u.get("id"), "email": u.get("email"),
                       "tier": u.get("tier")} for u in users]}


@app.post("/admin/beta/revoke")
def beta_revoke(_: None = Depends(require_admin)):
    """Revoke ALL beta-tagged users back to free (run when going live on Razorpay).
    Only touches users tagged tier_source='beta', real paying users are untouched."""
    store = get_store()
    revoked = []
    for u in store.list_users():
        if (u or {}).get("tier_source") == "beta":
            uid = u.get("uid") or u.get("id")
            if uid:
                store.set_tier(uid, "free", source="revoked")
                revoked.append(uid)
    return {"revoked": len(revoked), "uids": revoked}


# --------------------------------------------------------------------------- #
# access codes: hashed beta / discount codes. Admin generates (plaintext shown
# once); users redeem to unlock. Only salted hashes are stored, so a DB leak
# reveals neither the codes nor the order issued.
# --------------------------------------------------------------------------- #
class CodeGenRequest(BaseModel):
    kind: Literal["beta", "discount"] = "beta"
    count: int = Field(1, ge=1, le=200)
    tier: str = "enterprise"                      # beta codes grant this tier
    discount_pct: int = Field(0, ge=0, le=100)    # discount codes give this % off
    max_uses: int = Field(1, ge=1, le=100_000)
    expires_days: Optional[int] = Field(None, ge=1, le=3650)


@app.post("/admin/codes/generate")
def codes_generate(req: CodeGenRequest, _: None = Depends(require_admin)):
    if req.kind == "beta" and req.tier not in TIERS:
        raise HTTPException(400, f"Unknown tier; choose from {list(TIERS)}")
    if req.kind == "discount" and not (1 <= req.discount_pct <= 100):
        raise HTTPException(400, "discount_pct must be 1-100 for a discount code")
    store = get_store()
    now = datetime.now(timezone.utc)
    exp = (now + timedelta(days=req.expires_days)).isoformat() if req.expires_days else None
    plaintext = []
    for _i in range(req.count):
        code = generate_plaintext()
        meta = {"kind": req.kind, "max_uses": req.max_uses, "uses": 0, "redeemed_by": [],
                "active": True, "expires_at": exp, "created_at": now.isoformat()}
        if req.kind == "beta":
            meta["tier"] = req.tier
        else:
            meta["discount_pct"] = req.discount_pct
        store.code_create(hash_code(code), meta)
        plaintext.append(code)
    return {"kind": req.kind, "count": len(plaintext), "codes": plaintext,
            "note": "Shown once. Copy and share now, only salted hashes are stored."}


@app.get("/admin/codes")
def codes_list(_: None = Depends(require_admin)):
    """Redacted code list (hash-prefix id + metadata; never the plaintext)."""
    return {"codes": get_store().list_codes()}


class RedeemRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=64)


@app.post("/v1/redeem")
def redeem(req: RedeemRequest, p: Principal = Depends(require_principal)):
    """Redeem a beta (tier-granting) or discount code. Rate-limited; generic
    errors so it can't be used to enumerate codes."""
    enforce_quota(p)
    store = get_store()
    res = store.code_redeem(hash_code(req.code), p.user_id)
    if not res.get("ok"):
        raise HTTPException(400, res.get("reason") or "Invalid code.")
    meta = res["meta"]
    if meta.get("kind") == "discount":
        pct = int(meta.get("discount_pct", 0))
        store.set_discount(p.user_id, pct)
        return {"kind": "discount", "discount_pct": pct,
                "message": f"{pct}% discount applied to your next subscription."}
    tier = meta.get("tier", "enterprise")
    if tier not in TIERS:
        tier = "enterprise"
    store.upsert_user(p.user_id, None)
    store.set_tier(p.user_id, tier, source="beta")   # revocable via /admin/beta/revoke
    return {"kind": "beta", "granted": tier,
            "message": f"Access unlocked: {TIERS[tier].label}."}


@app.post("/admin/users/{uid}/reset-birth")
def admin_reset_birth(uid: str, _: None = Depends(require_admin)):
    """Clear a user's saved birth lock (support: typo in DOB/place, or a genuine
    re-assignment). The next birth-based call re-locks to the new person."""
    get_store().clear_birth_lock(uid)
    return {"uid": uid, "birth_lock": None}


# --------------------------------------------------------------------------- #
# birth-details change requests: user asks (with a reason) -> admin approves the
# unlock. Self-serve alternative to "contact support".
# --------------------------------------------------------------------------- #
class BirthChangeRequestIn(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)


@app.post("/v1/birth-change-request")
def birth_change_request(req: BirthChangeRequestIn, p: Principal = Depends(require_principal)):
    enforce_quota(p)
    store = get_store()
    lock = store.get_birth_lock(p.user_id)
    if not lock:
        raise HTTPException(400, "There are no saved birth details to change.")
    if store.user_open_change_request(p.user_id):
        raise HTTPException(409, "You already have a change request awaiting review.")
    rid = uuid.uuid4().hex
    store.create_change_request({
        "id": rid, "uid": p.user_id, "reason": req.reason, "status": "pending",
        "current": {"name": lock.get("name"), "date": lock.get("date"),
                    "time": lock.get("time"), "place": lock.get("place")},
        "created_at": datetime.now(timezone.utc).isoformat()})
    return {"id": rid, "status": "pending",
            "message": "Your change request has been submitted for review."}


@app.get("/admin/birth-change-requests")
def admin_list_change_requests(_: None = Depends(require_admin)):
    return {"requests": get_store().list_change_requests(status="pending")}


def _resolve_change_request(rid: str, decision: str) -> dict:
    store = get_store()
    r = store.get_change_request(rid)
    if not r:
        raise HTTPException(404, "Unknown request")
    if r.get("status") != "pending":
        raise HTTPException(409, f"Request already {r.get('status')}.")
    if decision == "approved":
        store.clear_birth_lock(r["uid"])     # unlock so the user can re-enter details
    store.update_change_request(rid, {"status": decision,
                                      "resolved_at": datetime.now(timezone.utc).isoformat()})
    return {"id": rid, "uid": r["uid"], "status": decision}


@app.post("/admin/birth-change-requests/{rid}/approve")
def admin_approve_change(rid: str, _: None = Depends(require_admin)):
    return _resolve_change_request(rid, "approved")


@app.post("/admin/birth-change-requests/{rid}/reject")
def admin_reject_change(rid: str, _: None = Depends(require_admin)):
    return _resolve_change_request(rid, "rejected")


@app.post("/admin/codes/{code_id}/deactivate")
def codes_deactivate(code_id: str, _: None = Depends(require_admin)):
    if not get_store().code_set_active(code_id, False):
        raise HTTPException(404, "Unknown code id")
    return {"id": code_id, "active": False}


@app.post("/admin/codes/{code_id}/reactivate")
def codes_reactivate(code_id: str, _: None = Depends(require_admin)):
    if not get_store().code_set_active(code_id, True):
        raise HTTPException(404, "Unknown code id")
    return {"id": code_id, "active": True}


# --------------------------------------------------------------------------- #
# checkout: start a subscription, applying any redeemed discount. Creates a real
# Razorpay order when live keys are configured; otherwise returns the priced
# intent (so the UI can show the discounted amount before payments go live).
# --------------------------------------------------------------------------- #
class CheckoutRequest(BaseModel):
    tier: str


@app.post("/v1/checkout")
def checkout(req: CheckoutRequest, p: Principal = Depends(require_principal)):
    if req.tier not in TIERS or req.tier == "free":
        raise HTTPException(400, "Choose a paid tier (basic, pro, enterprise).")
    enforce_quota(p)
    s = get_settings()
    t = TIERS[req.tier]
    user = get_store().get_user(p.user_id) or {}
    discount = max(0, min(100, int(user.get("discount_pct") or 0)))
    original = int(t.price_inr_month)
    amount = round(original * (100 - discount) / 100)
    base = {"tier": req.tier, "tier_label": t.label, "original_inr": original,
            "discount_pct": discount, "amount_inr": amount, "currency": "INR"}

    if s.payments_provider == "razorpay" and keys_configured(s.razorpay_key_id, s.razorpay_key_secret):
        notes = {"user_id": p.user_id, "tier": req.tier, "discount_pct": discount}
        plan_id = s.razorpay_plan_map().get(req.tier)
        if plan_id:                                    # recurring subscription (preferred)
            offer_id = s.razorpay_offer_map().get(req.tier) if discount else None
            sub = create_razorpay_subscription(plan_id, s.razorpay_key_id, s.razorpay_key_secret,
                                               notes=notes, offer_id=offer_id)
            return {**base, "provider": "razorpay", "enabled": True, "mode": "subscription",
                    "key_id": s.razorpay_key_id, "subscription_id": sub.get("id"), "name": "Nakshatra"}
        order = create_razorpay_order(                  # fallback: one-time order
            amount, s.razorpay_key_id, s.razorpay_key_secret, notes=notes,
            receipt=f"{req.tier}-{p.user_id[:12]}")
        return {**base, "provider": "razorpay", "enabled": True, "mode": "order",
                "key_id": s.razorpay_key_id, "order_id": order.get("id"), "name": "Nakshatra"}
    # Live payments not enabled yet: return the priced intent for the UI.
    return {**base, "provider": "none", "enabled": False,
            "message": "Live payments are being enabled. Use an access code to unlock in the meantime."}


@app.post("/v1/subscription/cancel")
def cancel_subscription(p: Principal = Depends(require_principal)):
    """Self-serve cancel: cancels the user's recurring subscription at cycle end
    (they keep paid access until then). The webhook handles the eventual downgrade."""
    s = get_settings()
    user = get_store().get_user(p.user_id) or {}
    sub_id = user.get("subscription_id")
    if not sub_id:
        raise HTTPException(400, "No active subscription on file.")
    if not (s.payments_provider == "razorpay" and keys_configured(s.razorpay_key_id, s.razorpay_key_secret)):
        raise HTTPException(503, "Payments are not enabled.")
    cancel_razorpay_subscription(sub_id, s.razorpay_key_id, s.razorpay_key_secret, at_cycle_end=True)
    return {"status": "cancelling", "message": "Your subscription will end at the close of the current cycle."}


@app.post("/webhooks/payments")
async def payments_webhook(request: Request):
    """Provider-signed webhook → tier change (subscription) or top-up (one-time).

    MONEY PATH: the signature is verified over the RAW body and every entity is
    marked processed before crediting, so retries never double-credit. Client
    "I paid" claims are never trusted, only this signed callback mutates credits.
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


# --------------------------------------------------------------------------- #
# payments: customer view, refund requests, admin approval, reconciliation
# --------------------------------------------------------------------------- #
@app.get("/v1/me/payments")
def my_payments(p: Principal = Depends(require_principal)):
    return {"payments": get_store().list_payments(p.user_id)}


class RefundRequestIn(BaseModel):
    payment_id: str = Field(..., max_length=64)
    reason: str = Field("", max_length=500)


@app.post("/v1/refunds")
def request_refund(req: RefundRequestIn, p: Principal = Depends(require_principal)):
    pay = get_store().get_payment(req.payment_id)
    if not pay or pay.get("uid") != p.user_id:        # 404, don't reveal others' payments
        raise HTTPException(404, "Payment not found")
    if pay.get("status") == "refunded":
        raise HTTPException(409, "This payment is already refunded")
    rid = uuid.uuid4().hex
    get_store().refund_request_create(rid, {
        "uid": p.user_id, "payment_id": req.payment_id, "reason": req.reason, "status": "pending"})
    return {"id": rid, "status": "pending"}


@app.get("/v1/refunds")
def my_refunds(p: Principal = Depends(require_principal)):
    return {"requests": [r for r in get_store().list_refund_requests() if r.get("uid") == p.user_id]}


@app.get("/admin/refunds")
def admin_list_refunds(status: str = "pending", _: None = Depends(require_admin)):
    return {"requests": get_store().list_refund_requests(status)}


def _process_refund(payment_id: str) -> dict:
    """Trigger a refund. In prod this calls the Razorpay refund API and the real
    webhook reverses credits; here (dev) we fire the signed mock refund webhook."""
    secret = _payments_secret()
    _rid, raw, sig = _mock_refund_event(payment_id, secret)
    return handle_razorpay_webhook(raw, sig, secret, get_store(), TIERS)


@app.post("/admin/refunds/{rid}/approve")
def admin_approve_refund(rid: str, _: None = Depends(require_admin)):
    r = get_store().refund_request_get(rid)
    if not r:
        raise HTTPException(404, "Unknown refund request")
    if r.get("status") != "pending":
        raise HTTPException(409, f"Request already {r.get('status')}")
    result = _process_refund(r["payment_id"])
    get_store().refund_request_set_status(rid, "approved")
    return {"status": "approved", "refund": result}


@app.post("/admin/refunds/{rid}/reject")
def admin_reject_refund(rid: str, _: None = Depends(require_admin)):
    r = get_store().refund_request_get(rid)
    if not r:
        raise HTTPException(404, "Unknown refund request")
    get_store().refund_request_set_status(rid, "rejected")
    return {"status": "rejected"}


@app.get("/admin/economics")
def admin_economics(utilization: float = 1.0, readings: int = 30, _: None = Depends(require_admin)):
    """Live unit economics + monthly run-cost projection from current tiers + rates."""
    tiers = [pricing.tier_economics(k, t.price_inr_month, t.monthly_tokens,
                                    utilization=utilization, readings_per_month=readings).__dict__
             for k, t in TIERS.items() if t.price_inr_month]
    gate = []
    for k, t in TIERS.items():
        if not t.monthly_tokens:
            continue
        net = t.price_inr_month / (1 + pricing.GST_PCT)
        worst = t.monthly_tokens * pricing.PLAN_INR_PER_TOKEN
        gate.append({"tier": k, "price_inr": t.price_inr_month, "grant": t.monthly_tokens,
                     "gated_grant": pricing.gated_grant_tokens(t.price_inr_month),
                     "is_gated": pricing.tier_is_gated(t.price_inr_month, t.monthly_tokens),
                     "worst_case_margin_pct": round((net - worst - t.price_inr_month * pricing.RAZORPAY_FEE_PCT * (1 + pricing.GST_PCT)) / net * 100, 1)})
    return {
        "gate": gate,
        "plan_inr_per_token": pricing.PLAN_INR_PER_TOKEN,
        "rates": {"usd_inr": pricing.USD_INR, "gemini_in_usd_per_1m": pricing.GEMINI_IN_USD_PER_1M,
                  "gemini_out_usd_per_1m": pricing.GEMINI_OUT_USD_PER_1M,
                  "razorpay_pct": pricing.RAZORPAY_FEE_PCT, "gst_pct": pricing.GST_PCT},
        "reading_cost_inr": round(pricing.reading_cost_inr(), 2),
        "chat_inr_per_1k_tokens": round(pricing.chat_inr_per_token() * 1000, 3),
        "tiers": tiers,
        "platform_cost_projection": [pricing.monthly_platform_cost(n) for n in (100, 1000, 10000)],
    }


@app.get("/admin/reconcile/{uid}")
def admin_reconcile(uid: str, _: None = Depends(require_admin)):
    """Money truth for a user: payments vs ledger ('did they actually pay')."""
    store = get_store()
    payments = store.list_payments(uid)
    ledger = store.credit_ledger(uid, limit=1000)
    captured = sum(int(p.get("amount_inr", 0)) for p in payments if p.get("status") == "captured")
    refunded = sum(int(p.get("amount_inr", 0)) for p in payments if p.get("status") == "refunded")
    credited_tokens = sum(int(e.get("tokens", 0)) for e in ledger if e.get("type") in ("grant", "topup"))
    refunded_tokens = sum(int(e.get("tokens", 0)) for e in ledger if e.get("type") == "refund")
    return {"uid": uid, "payments": payments, "ledger": ledger,
            "summary": {"captured_inr": captured, "refunded_inr": refunded,
                        "credited_tokens": credited_tokens, "refunded_tokens": refunded_tokens}}


# --------------------------------------------------------------------------- #
# admin: abuse controls (bans), anomaly flagging, analytics
# --------------------------------------------------------------------------- #
class BanIn(BaseModel):
    kind: Literal["temporary", "permanent"] = "temporary"
    reason: str = Field("policy violation", max_length=200)
    days: int = Field(7, ge=1, le=3650)


@app.post("/admin/users/{uid}/ban")
def admin_ban(uid: str, req: BanIn, _: None = Depends(require_admin)):
    until = (datetime.now(timezone.utc) + timedelta(days=req.days)) if req.kind == "temporary" else None
    get_store().set_ban(uid, req.kind, req.reason, until, by="admin")
    return {"uid": uid, "kind": req.kind, "reason": req.reason,
            "until": until.isoformat() if until else None}


@app.post("/admin/users/{uid}/unban")
def admin_unban(uid: str, _: None = Depends(require_admin)):
    get_store().clear_ban(uid)
    return {"uid": uid, "status": "unbanned"}


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _scan_anomalies() -> list[dict]:
    """Flag users on token velocity, refund abuse, and accounts sharing an IP."""
    s = get_settings()
    store = get_store()
    users = store.list_users()
    refund_counts: dict = {}
    for r in store.list_refund_requests():
        refund_counts[r.get("uid")] = refund_counts.get(r.get("uid"), 0) + 1
    acts, ip_map = {}, {}
    for u in users:
        a = store.get_activity(u["uid"]) or {}
        acts[u["uid"]] = a
        if a.get("last_ip"):
            ip_map.setdefault(a["last_ip"], []).append(u["uid"])
    flagged = []
    for u in users:
        uid = u["uid"]
        a = acts.get(uid, {})
        usage = store.usage_today(uid) or {}
        tokens = int(usage.get("tokens_in", 0)) + int(usage.get("tokens_out", 0))
        reasons = []
        if tokens >= s.anomaly_token_day_flag:
            reasons.append(f"high token use today ({tokens:,})")
        if refund_counts.get(uid, 0) >= s.anomaly_refund_flag:
            reasons.append(f"refund abuse ({refund_counts[uid]} requests)")
        ip = a.get("last_ip")
        if ip and len(ip_map.get(ip, [])) >= s.anomaly_ip_accounts_flag:
            reasons.append(f"{len(ip_map[ip])} accounts share IP {ip}")
        if reasons:
            flagged.append({"uid": uid, "reasons": reasons, "last_ip": ip,
                            "last_seen": _iso(a.get("last_seen")), "tier": u.get("tier"),
                            "banned": bool(store.get_ban(uid))})
    return flagged


@app.get("/admin/ping")
def admin_ping(_: None = Depends(require_admin)):
    return {"admin": True}


@app.get("/admin/anomalies")
def admin_anomalies(_: None = Depends(require_admin)):
    return {"flagged": _scan_anomalies()}


@app.get("/admin/stats")
def admin_stats(_: None = Depends(require_admin)):
    """One-stop analytics: users, traffic, tokens, revenue, refunds, run-cost."""
    store = get_store()
    users = store.list_users()
    pays = store.all_payments()
    revenue = sum(int(p.get("amount_inr", 0)) for p in pays if p.get("status") == "captured")
    refunded = sum(int(p.get("amount_inr", 0)) for p in pays if p.get("status") == "refunded")
    return {"users_total": len(users), "banned": len(store.list_bans()),
            "flagged": len(_scan_anomalies()), "tokens_today": store.global_tokens_today(),
            "revenue_inr": revenue, "refunded_inr": refunded, "net_inr": revenue - refunded,
            "platform_cost": pricing.monthly_platform_cost(max(len(users), 1))}


# --- mock Razorpay gateway (DEV ONLY) ---------------------------------------- #
class MockCheckoutIn(BaseModel):
    kind: Literal["subscription", "topup"]
    tier: Optional[str] = None
    amount_inr: Optional[int] = None
    uid: Optional[str] = None          # dev override (e.g. stress tests); defaults to caller


class MockRefundIn(BaseModel):
    payment_id: str = Field(..., max_length=64)


@app.post("/mock/razorpay/checkout")
def mock_checkout(req: MockCheckoutIn, p: Principal = Depends(require_principal)):
    if get_settings().is_prod:
        raise HTTPException(404, "Not found")
    uid = req.uid or p.user_id
    amount = req.amount_inr
    if req.kind == "subscription":
        if req.tier not in TIERS:
            raise HTTPException(422, "Unknown tier")
        amount = amount or TIERS[req.tier].price_inr_month
    elif amount not in TOPUP_PACKS:
        raise HTTPException(422, f"amount_inr must be one of {sorted(TOPUP_PACKS)}")
    secret = _payments_secret()
    pid, raw, sig = _mock_checkout_event(req.kind, uid, secret, tier=req.tier, amount_inr=amount)
    result = handle_razorpay_webhook(raw, sig, secret, get_store(), TIERS)
    return {"payment_id": pid, **result}


@app.post("/mock/razorpay/refund")
def mock_refund(req: MockRefundIn, _: None = Depends(require_admin)):
    if get_settings().is_prod:
        raise HTTPException(404, "Not found")
    return _process_refund(req.payment_id)
