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

import json
import logging
import re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
from .gating import filter_chart_for_features, filter_findings, locked_topic, _TOPIC_LABEL
from .codes import generate_plaintext, hash_code
from .engine import rectify_birth_time, engine_version
from .rules import derive_findings, derive_prashna, derive_btr, chart_facts
from .match import ashtakoot, is_manglik, NAKSHATRAS as MATCH_NAKSHATRAS
from .knowledge import SIGNS
from .llm import chat_answer, render_reading, looks_like_injection, compatibility_summary, DISCLAIMERS
from . import fraud
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


@app.middleware("http")
async def _limit_body_size(request: Request, call_next):
    """Reject oversized request bodies early (anti-DoS / memory-amplification). The
    payments webhook reads the raw body BEFORE auth, so this guards it pre-auth too.
    Bodies without a Content-Length (chunked) are bounded by the Cloud Run platform cap."""
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > get_settings().max_request_bytes:
                return JSONResponse({"detail": "Request body too large."}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)
    return await call_next(request)


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
    latest = store.user_latest_change_request(p.user_id)
    notice = None
    if latest and latest.get("status") in ("approved", "rejected") and not latest.get("acked"):
        notice = {"id": latest.get("id"), "status": latest.get("status")}
    # Live fraud-risk banner (immediate, reflects this user's own signals; the batch
    # scan adds cross-user context like shared-IP and can auto-suspend).
    usage = store.usage_today(p.user_id) or {}
    risk = fraud.compute_risk(user, {"tokens_today": int(usage.get("tokens_in", 0)) + int(usage.get("tokens_out", 0))},
                              get_settings())
    return {"user_id": p.user_id, "tier": p.tier.key,
            "sections": sorted(p.tier.sections), "features": sorted(p.tier.features),
            "discount_pct": int(user.get("discount_pct") or 0),
            "consent_version": user.get("consent_version"),
            "adult_confirmed": bool(user.get("adult_confirmed")),
            "nominee": user.get("nominee"),
            "grievance_officer": {"name": get_settings().grievance_officer_name or None,
                                  "email": get_settings().grievance_officer_email or None},
            "birth_lock": user.get("birth_lock"),
            "birth_change_pending": bool(store.user_open_change_request(p.user_id)),
            "birth_change_notice": notice,
            "risk_notice": fraud.risk_banner(risk["band"]),
            "has_subscription": bool(user.get("subscription_id")),
            "balance": store.credit_balance(p.user_id, p.tier)}


class FeedbackIn(BaseModel):
    message: str = Field(..., min_length=3, max_length=2000)
    category: str = Field("general", max_length=24)
    rating: Optional[int] = Field(None, ge=1, le=5)
    page: Optional[str] = Field(None, max_length=80)


@app.post("/v1/feedback")
def submit_feedback(req: FeedbackIn, p: Principal = Depends(require_principal)):
    """Capture user feedback (idea/bug/praise/etc.) for later review in Admin."""
    store = get_store()
    u = store.get_user(p.user_id) or {}
    store.add_feedback({
        "uid": p.user_id, "email": u.get("email"), "tier": p.tier.key,
        "message": req.message.strip(), "category": req.category,
        "rating": req.rating, "page": req.page,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True}


class ConsentIn(BaseModel):
    version: str = Field(..., max_length=32)
    is_adult: bool = False        # the user attests they meet the minimum age (DPDP s9 / GDPR Art 8)


@app.post("/v1/consent")
def record_consent(req: ConsentIn, p: Principal = Depends(require_principal)):
    """Record the user's consent to process their (sensitive) birth data. Auditable
    record for DPDP/GDPR; the web captures it before the first cast. We require an
    age attestation here: DPDP s9 forbids onboarding/behaviourally-monitoring a child
    (under 18) without verifiable parental consent, which we do not yet support, so we
    do not knowingly onboard minors at all."""
    if not req.is_adult:
        raise HTTPException(403, f"You must be at least {get_settings().min_user_age} "
                                 "years old to use Nakshatra.")
    store = get_store()
    store.upsert_user(p.user_id, None)
    store.set_consent(p.user_id, req.version, is_adult=True)
    return {"ok": True, "version": req.version}


@app.post("/v1/consent/withdraw")
def withdraw_consent(p: Principal = Depends(require_principal)):
    """Withdraw consent (DPDP s6 / GDPR Art 7) — must be as easy as giving it. We stop
    processing birth data (the user must consent again to use the service); this does not
    by itself erase data — DELETE /v1/me does that."""
    get_store().withdraw_consent(p.user_id)
    return {"ok": True,
            "message": "Consent withdrawn. We will not process your birth data until you "
                       "consent again. To also erase your stored data, delete your account.",
            "erase_endpoint": "DELETE /v1/me"}


class GrievanceIn(BaseModel):
    message: str = Field(..., min_length=5, max_length=4000)
    category: str = Field("privacy", max_length=24)


@app.post("/v1/grievance")
def file_grievance(req: GrievanceIn, p: Principal = Depends(require_principal)):
    """File a data-privacy grievance (DPDP s13). Recorded for the Grievance Officer."""
    s = get_settings()
    store = get_store()
    u = store.get_user(p.user_id) or {}
    store.add_grievance({
        "uid": p.user_id, "email": u.get("email"), "tier": p.tier.key,
        "message": req.message.strip(), "category": req.category, "status": "open",
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True,
            "officer": {"name": s.grievance_officer_name or None,
                        "email": s.grievance_officer_email or None},
            "message": "Your grievance has been recorded. We will respond within the "
                       "timeframe required by law."}


class NomineeIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: Optional[str] = Field(None, max_length=200)
    relationship: Optional[str] = Field(None, max_length=80)

    @field_validator("email")
    @classmethod
    def _email_ok(cls, v):
        if v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v.strip()):
            raise ValueError("invalid email")
        return v.strip() if v else v


@app.get("/v1/nominee")
def get_nominee(p: Principal = Depends(require_principal)):
    """The Data Principal's nominee (DPDP s14) — who may exercise their rights on death/incapacity."""
    return {"nominee": (get_store().get_user(p.user_id) or {}).get("nominee")}


@app.post("/v1/nominee")
def set_nominee(req: NomineeIn, p: Principal = Depends(require_principal)):
    store = get_store()
    store.upsert_user(p.user_id, None)
    store.set_nominee(p.user_id, req.model_dump())
    return {"ok": True, "nominee": req.model_dump()}


@app.delete("/v1/nominee")
def clear_nominee(p: Principal = Depends(require_principal)):
    get_store().set_nominee(p.user_id, None)
    return {"ok": True}


# Sub-processors / recipients of personal data — disclosed in the data export so the
# user sees who their data is shared with (DPDP s11 / GDPR Art 15(1)(c), Art 20).
SUBPROCESSORS = [
    {"name": "Google Cloud / Firebase", "purpose": "hosting, authentication, Firestore database",
     "region": "asia-south1 (India)"},
    {"name": "Google Vertex AI / Gemini", "purpose": "LLM phrasing of readings/chat from computed findings",
     "region": "global"},
    {"name": "Razorpay", "purpose": "payment processing", "region": "India"},
]


@app.get("/v1/me/export")
def me_export(p: Principal = Depends(require_principal)):
    """Data portability (DPDP s11 / GDPR Art 20): the user's own stored data — profile,
    ledger, chats, payment history — plus the list of recipients (sub-processors)."""
    data = get_store().export_user(p.user_id)
    data["recipients"] = SUBPROCESSORS
    data["exported_at"] = datetime.now(timezone.utc).isoformat()
    return data


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


def _meter_precheck(p: Principal) -> None:
    """Block an LLM call when out of credits OR over the daily abuse ceiling.
    Applies to every metered LLM endpoint (reading/chat/prashna/btr), not just chat."""
    if not p.tier.monthly_tokens:
        return
    s = get_settings()
    bal = get_store().credit_balance(p.user_id, p.tier)
    if bal["available"] <= 0:
        raise HTTPException(402, "You're out of credits for this cycle, upgrade or add a top-up.")
    if bal.get("daily_used", 0) >= s.daily_token_ceiling:
        raise HTTPException(429, "Daily limit reached, please try again tomorrow.")


def _meter_debit(p: Principal, ti: int, to: int, reason: str, ref: Optional[str] = None) -> None:
    """Debit the metered allowance for an LLM render and record usage (prashna/btr)."""
    cost = int(ti) + int(to)
    store = get_store()
    if cost:
        store.credit_debit(p.user_id, p.tier, cost, reason=reason, ref=ref)
    store.record(p.key, ti, to, reading=True)
    store.add_user_tokens(p.user_id, cost)


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
    # readings draw on the same metered AI allowance as chat (credits + daily ceiling)
    _meter_precheck(p)
    resp = get_reading(birth, p.tier)
    if "varshphal" not in p.tier.features:        # Tajik annual block is Pro+
        resp.varshphal = None
    cost = int(resp.meta.tokens_in) + int(resp.meta.tokens_out)
    if cost:                                  # cache hits cost 0 tokens -> free
        store.credit_debit(p.user_id, p.tier, cost, reason="reading", ref=resp.meta.chart_hash)
    store.record(p.key, resp.meta.tokens_in, resp.meta.tokens_out, reading=True)
    store.add_user_tokens(p.user_id, int(resp.meta.tokens_in) + int(resp.meta.tokens_out))
    return resp


# --------------------------------------------------------------------------- #
# grounded chat (metered on the token credit ledger; see docs/CREDIT_LEDGER.md)
# --------------------------------------------------------------------------- #
class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    # match the message cap so a long prior turn can't 422 the request (history is
    # server-authoritative and ignored for grounding anyway; this is just defensive)
    text: str = Field(..., max_length=6000)


class ChatRequest(BaseModel):
    birth: BirthDetails                      # the cast chart this conversation is grounded in
    # 6000 so a pasted jailbreak (often 1-5k chars) still reaches the injection/abuse
    # screen and gets flagged + refused, rather than bouncing off validation unflagged.
    message: str = Field(..., min_length=1, max_length=6000)
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

    # --- real-time abuse block: destructive/hacking intent ("drop all the database",
    # rm -rf, SQLi, ...) is refused IMMEDIATELY with a generic reply, never reaches the
    # model, costs nothing, and is recorded as a high-severity (malicious) signal. ---
    if fraud.looks_malicious(req.message):
        try:
            store.record_jailbreak(p.user_id, req.message, kind="chat-malicious")
            log.warning("malicious chat blocked uid=%s", p.user_id)
        except Exception:  # noqa: BLE001
            pass
        chat_id = req.chat_id or uuid.uuid4().hex
        b = store.credit_balance(p.user_id, p.tier)
        return ChatResponse(answer=fraud.MALICIOUS_REFUSAL, tokens_used=0, chat_id=chat_id,
                            balance={"grant": b["grant"], "topup": b["topup"], "available": b["available"]})

    # --- tier topic gate: a question targeting a LOCKED technique (divisional charts,
    # KP/Ashtakavarga tables, Varshphal) is refused before the model is called, so it
    # can't be coaxed into fabricating analysis the user's tier doesn't include. ---
    locked = locked_topic(req.message, p.tier.features)
    if locked:
        chat_id = req.chat_id or uuid.uuid4().hex
        b = store.credit_balance(p.user_id, p.tier)
        return ChatResponse(
            answer=(f"{_TOPIC_LABEL[locked].capitalize()} aren't part of your current "
                    f"{p.tier.label} plan, so I can't read them here. Upgrade to unlock that, "
                    f"meanwhile I'm happy to go deeper on what your plan includes."),
            tokens_used=0, chat_id=chat_id,
            balance={"grant": b["grant"], "topup": b["topup"], "available": b["available"]})

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
    findings = filter_findings(derive_findings(chart), p.tier.sections, p.tier.features)
    facts = chart_facts(chart, p.tier.features)   # tier-gated literal positions for factual answers
    # Server-authoritative history: load prior turns from the store by chat_id; the
    # client-supplied req.history is IGNORED for grounding so a crafted client can't
    # inject fake turns. (Stateless if persistence is off or it's a new conversation.)
    chat_id = req.chat_id or uuid.uuid4().hex
    history = (store.chat_get_turns(p.user_id, chat_id, limit=16)
               if (req.chat_id and s.persist_chat) else [])
    # Flag jailbreak/injection attempts against the user (every modus operandi the
    # guard catches). Repeat offenders surface in Admin → Flagged users.
    injected = looks_like_injection(req.message)
    if injected:
        try:
            n = store.record_jailbreak(p.user_id, req.message, kind="chat")
            log.warning("jailbreak attempt uid=%s count=%s", p.user_id, n)
        except Exception:  # noqa: BLE001, never fail the request on flagging
            pass
    answer, _model, ti, to = chat_answer(findings, history, req.message, s.chat_max_output, facts)
    cost = int(ti) + int(to)

    # --- atomic debit on the ledger (grant first, then topup; never below 0) ---
    msg_id = uuid.uuid4().hex
    bal2 = store.credit_debit(p.user_id, p.tier, cost, reason="chat turn", ref=msg_id)

    # --- persist the turn (best-effort, opt-out via PERSIST_CHAT; not the money path).
    # Never persist an injection attempt: keep attack text out of the grounding history
    # so a single jailbreak can't poison the rest of the conversation. ---
    if s.persist_chat and not injected:
        try:
            store.chat_save_turn(p.user_id, chat_id, req.birth.chart_hash(),
                                 req.message, answer, cost, msg_id)
        except Exception as exc:  # noqa: BLE001, never log the message body (PII)
            log.warning("chat persistence failed (non-fatal) uid=%s chat_id=%s err=%s",
                        p.user_id, chat_id, type(exc).__name__)
    store.record(p.key, ti, to, reading=False)
    store.add_user_tokens(p.user_id, int(ti) + int(to))

    return ChatResponse(answer=answer, tokens_used=cost, chat_id=chat_id,
                        balance={"grant": bal2["grant"], "topup": bal2["topup"],
                                 "available": bal2["available"]})


# --------------------------------------------------------------------------- #
# Prashna / KP horary, a chart cast for the moment of asking (pro+)
# --------------------------------------------------------------------------- #
def _now_in_tz(tz: str) -> tuple[str, str]:
    """(YYYY-MM-DD, HH:MM) right now at a UTC offset like "+05:30" (UTC on parse fail)."""
    off = timedelta(0)
    m = re.fullmatch(r"([+-])(\d{1,2}):?(\d{2})", (tz or "").strip())   # strip first; no \s* backtracking
    if m:
        sign = 1 if m.group(1) == "+" else -1
        off = sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
    local = datetime.now(timezone.utc) + off
    return local.strftime("%Y-%m-%d"), local.strftime("%H:%M")


class MatchRequest(BaseModel):
    partner_name: Optional[str] = Field(None, max_length=80)
    date: str = Field(..., description="Partner birth date, YYYY-MM-DD")
    time: str = Field(..., description="Partner birth time, HH:MM")
    tz: str = Field("+05:30", max_length=40)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    self_gender: Literal["male", "female", "other"] = "male"

    @field_validator("date")
    @classmethod
    def _d(cls, v):
        if not re.fullmatch(_DATE_RE, v):
            raise ValueError("date must be YYYY-MM-DD")
        return v

    @field_validator("time")
    @classmethod
    def _t(cls, v):
        if not re.fullmatch(_TIME_RE, v):
            raise ValueError("time must be HH:MM (24h)")
        return v


def _match_inputs(chart: dict) -> dict:
    """Extract Moon nakshatra index, Moon rashi index, and Mars houses for matching."""
    cb = chart.get("chart", chart)
    planets = cb.get("planets") or {}
    moon = planets.get("Moon") or {}
    mars = planets.get("Mars") or {}
    asc_sign = (cb.get("asc") or {}).get("sign")
    moon_sign = moon.get("sign")
    nak_name = cb.get("moon_nakshatra") or moon.get("nakshatra")

    def sidx(s):
        return SIGNS.index(s) if s in SIGNS else None

    def nidx(n):
        if not n:
            return None
        nl = str(n).strip().lower()
        for i, name in enumerate(MATCH_NAKSHATRAS):
            if name.lower() == nl or name.lower().startswith(nl[:5]) or nl.startswith(name.lower()[:5]):
                return i
        return None

    def house(psign, ref):
        a, b = sidx(psign), sidx(ref)
        return ((a - b) % 12) + 1 if (a is not None and b is not None) else None

    return {"nak": nidx(nak_name), "rashi": sidx(moon_sign), "nak_name": nak_name,
            "moon_sign": moon_sign, "mars_lagna": house(mars.get("sign"), asc_sign),
            "mars_moon": house(mars.get("sign"), moon_sign)}


@app.post("/v1/match")
def kundali_match(req: MatchRequest, p: Principal = Depends(require_principal)):
    """Kundali Matching (Ashtakoot Guna Milan, 36 points) + Manglik compatibility:
    your locked chart vs a partner's. Deterministic (no LLM). FREE/BASIC get the
    headline (total score, verdict, dosha flags, Manglik); the full 8-koota
    breakdown unlocks on Pro."""
    enforce_quota(p)
    s = get_settings()
    store = get_store()
    lock = store.get_birth_lock(p.user_id)
    if not (lock and lock.get("date")):
        raise HTTPException(409, "Cast your own chart first (Natal tab), then match it against a partner.")
    self_chart = get_chart(BirthDetails(name=lock.get("name") or "You", date=lock["date"], time=lock["time"],
                                        tz=lock["tz"], lat=lock["lat"], lon=lock["lon"])).chart
    partner_chart = get_chart(BirthDetails(name=req.partner_name or "Partner", date=req.date, time=req.time,
                                           tz=req.tz, lat=req.lat, lon=req.lon)).chart
    si, pi = _match_inputs(self_chart), _match_inputs(partner_chart)
    if None in (si["nak"], si["rashi"], pi["nak"], pi["rashi"]):
        raise HTTPException(422, "Couldn't read the Moon's nakshatra/sign for one of the charts.")
    boy, girl = (pi, si) if req.self_gender == "female" else (si, pi)  # asymmetric kutas need groom/bride
    a = ashtakoot(boy["nak"], boy["rashi"], girl["nak"], girl["rashi"])
    sm, pm = is_manglik(si["mars_lagna"], si["mars_moon"]), is_manglik(pi["mars_lagna"], pi["mars_moon"])
    mnote = ("Neither chart is Manglik." if not sm and not pm else
             "Both charts are Manglik, traditionally considered to balance out." if sm and pm else
             "One chart is Manglik and the other is not, traditionally a point to weigh and remedy.")
    summary = (f"Guna Milan score {a['total']} of 36 ({a['verdict']}). "
               + ("A Nadi dosha is present (same Nadi). " if a["nadi_dosha"] else "")
               + ("A Bhakoot dosha is present. " if a["bhakoot_dosha"] else "") + mnote)
    # Free/Basic get the headline; the per-koota breakdown is the Pro upsell.
    detail = p.tier.key in ("pro", "enterprise")
    ashtakoot_out = a if detail else {k: a[k] for k in ("total", "max", "verdict", "nadi_dosha", "bhakoot_dosha")}
    # Pro+ also get an LLM-phrased summary grounded in the computed kutas (metered).
    ai_summary = None
    if detail:
        bal = store.credit_balance(p.user_id, p.tier)
        if bal["available"] > 0 and bal["daily_used"] < s.daily_token_ceiling:
            try:
                facts = {"total": a["total"], "max": 36, "verdict": a["verdict"], "kutas": a["kutas"],
                         "nadi_dosha": a["nadi_dosha"], "bhakoot_dosha": a["bhakoot_dosha"],
                         "manglik_self": sm, "manglik_partner": pm}
                text, ti, to = compatibility_summary(facts)
                _meter_debit(p, ti, to, "kundali-match")
                ai_summary = text
            except Exception:  # noqa: BLE001, never fail the match on the optional prose
                pass
    return {
        "self": {"nakshatra": si["nak_name"], "rashi": si["moon_sign"], "manglik": sm},
        "partner": {"nakshatra": pi["nak_name"], "rashi": pi["moon_sign"], "manglik": pm},
        "ashtakoot": ashtakoot_out,
        "detail_unlocked": detail,
        "manglik_match": {"self": sm, "partner": pm, "compatible": sm == pm, "note": mnote},
        "summary": summary, "ai_summary": ai_summary,
        "disclaimers": ["Guna Milan is one traditional compatibility lens, not a verdict on a relationship."],
    }


class PanchangRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    tz: str = Field("+05:30", max_length=40)


_GOCHAR_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]


@app.post("/v1/transits")
def transits(p: Principal = Depends(require_principal)):
    """Gochar (current transits) over the user's natal chart: where each planet is
    moving now and which natal house it activates, plus Sade Sati and the Saturn-
    Jupiter double transit. Deterministic (no LLM). Basic+ (uses your saved chart)."""
    if p.tier.key == "free":
        raise HTTPException(402, "Transits (Gochar) are available from the Basic plan.")
    enforce_quota(p)
    store = get_store()
    lock = store.get_birth_lock(p.user_id)
    if not (lock and lock.get("date")):
        raise HTTPException(409, "Cast your own chart first (Natal tab) to read transits over it.")
    natal = get_chart(BirthDetails(name=lock.get("name") or "You", date=lock["date"], time=lock["time"],
                                   tz=lock["tz"], lat=lock["lat"], lon=lock["lon"])).chart
    cb = natal.get("chart", natal)
    asc_sign = (cb.get("asc") or {}).get("sign")
    asc_idx = SIGNS.index(asc_sign) if asc_sign in SIGNS else None
    d, t = _now_in_tz(lock["tz"])
    now_chart = get_chart(BirthDetails(date=d, time=t, tz=lock["tz"], lat=lock["lat"], lon=lock["lon"])).chart
    now_planets = (now_chart.get("chart", now_chart).get("planets")) or {}
    rows = []
    for name in _GOCHAR_PLANETS:
        pl = now_planets.get(name) or {}
        sign = pl.get("sign")
        if not sign:
            continue
        house = (((SIGNS.index(sign) - asc_idx) % 12) + 1) if (sign in SIGNS and asc_idx is not None) else None
        rows.append({"planet": name, "sign": sign, "house": house,
                     "retrograde": bool((pl.get("status") or {}).get("retrograde", pl.get("retrograde", False)))})
    cur = (((natal.get("dasha_systems") or {}).get("vimshottari") or {}).get("current")) or {}
    return {
        "date": d, "ascendant": asc_sign, "transits": rows,
        "sade_sati": natal.get("sade_sati"), "double_transit": natal.get("double_transit"),
        "current_dasha": {"mahadasha": cur.get("mahadasha"), "antardasha": cur.get("antardasha")},
    }


@app.post("/v1/panchang")
def panchang(req: PanchangRequest, p: Principal = Depends(require_principal)):
    """Daily Vedic almanac for the user's place (tithi, nakshatra, yoga, karana,
    vara, moon phase, hora). Deterministic (no LLM, no credit); all signed-in users."""
    enforce_quota(p)
    d, t = _now_in_tz(req.tz)
    chart = get_chart(BirthDetails(date=d, time=t, tz=req.tz, lat=req.lat, lon=req.lon)).chart
    pan = chart.get("panchang") or {}
    return {
        "date": d, "time": t, "tz": req.tz,
        "tithi": pan.get("tithi"), "nakshatra": pan.get("nakshatra"),
        "yoga": pan.get("yoga"), "karana": pan.get("karana"), "vara": pan.get("vara"),
        "moon_phase": chart.get("moon_phase"), "hora": chart.get("hora"),
    }


class PrashnaRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    tz: str = Field("+05:30", max_length=40)        # bounded: flows into the engine
    category: Optional[str] = Field(None, max_length=40)


@app.post("/v1/prashna", response_model=ReadingResponse)
def prashna(req: PrashnaRequest, p: Principal = Depends(require_principal)):
    if p.tier.key not in ("pro", "enterprise"):
        raise HTTPException(402, "Prashna (KP horary) is available on Pro and Enterprise.")
    enforce_quota(p)
    enforce_global_breaker()
    _bad = fraud.looks_malicious(req.question)
    if _bad or looks_like_injection(req.question):         # the free-text question is an abuse vector too
        try:
            get_store().record_jailbreak(p.user_id, req.question,
                                         kind="prashna-malicious" if _bad else "prashna")
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(400, "Please ask a genuine horary question about your life.")
    _meter_precheck(p)                                     # credits + daily ceiling
    d, t = _now_in_tz(req.tz)                              # cast for the moment of asking
    birth = BirthDetails(date=d, time=t, tz=req.tz, lat=req.lat, lon=req.lon)
    cr = get_chart(birth)
    findings = derive_prashna(cr.chart, req.question, req.category)
    summary, sections, model_name, ti, to = render_reading(cr.chart, findings, {"prashna"})
    meta = Meta(engine_version=cr.meta.engine_version, rules_version=RULES_VERSION,
                renderer_version=RENDERER_VERSION, model=model_name, tier=p.tier.key,
                report_type="prashna", cache_hit=False, tokens_in=ti, tokens_out=to,
                chart_hash=birth.chart_hash())
    _meter_debit(p, ti, to, "prashna")
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
    _meter_precheck(p)                    # credits + daily ceiling (BTR is a real LLM render)
    enforce_birth_lock(p.user_id, req)   # BTR refines time on the SAME person (date+place must match)
    payload = req.model_dump()
    payload["events"] = [e.model_dump() for e in req.events]
    rect = rectify_birth_time(payload)
    findings, norm = derive_btr(rect, payload)
    summary, sections, model_name, ti, to = render_reading(rect, findings, {"btr"})
    meta = Meta(engine_version=engine_version(), rules_version=RULES_VERSION,
                renderer_version=RENDERER_VERSION, model=model_name, tier=p.tier.key,
                report_type="btr", cache_hit=False, tokens_in=ti, tokens_out=to)
    _meter_debit(p, ti, to, "btr")
    return BtrResponse(summary=summary, sections=sections, findings=findings,
                       disclaimers=DISCLAIMERS, meta=meta, rectification=norm)


# --------------------------------------------------------------------------- #
# async readings
# --------------------------------------------------------------------------- #
def _run_job(job_id: str, birth: BirthDetails, tier_key: str, key: str, uid: str):
    store = get_store()
    tier = TIERS[tier_key]
    store.job_put(job_id, {"job_id": job_id, "status": "running", "owner": key})
    try:
        resp = get_reading(birth, tier)
        cost = int(resp.meta.tokens_in) + int(resp.meta.tokens_out)
        if cost:                                  # async readings debit the SAME metered allowance
            store.credit_debit(uid, tier, cost, reason="reading (async)", ref=resp.meta.chart_hash)
        store.record(key, resp.meta.tokens_in, resp.meta.tokens_out, reading=True)
        store.add_user_tokens(uid, cost)
        store.job_put(job_id, {"job_id": job_id, "status": "done", "owner": key, "result": resp.model_dump()})
    except Exception:  # noqa: BLE001
        # Keep the real exception in server logs only; never surface str(exc) to the
        # client (it can carry Firestore paths / project ids / engine internals).
        log.exception("job failed")
        store.job_put(job_id, {"job_id": job_id, "status": "error", "owner": key,
                               "error": "Reading failed. Please try again."})


@app.post("/v1/reading/async", response_model=JobResponse)
def reading_async(birth: BirthDetails, background: BackgroundTasks, p: Principal = Depends(require_principal)):
    if not p.tier.reading_allowed:
        raise HTTPException(402, "Readings not included in this tier.")
    if not p.tier.allow_async:
        raise HTTPException(402, f"Async readings require Pro or higher (current: {p.tier.label}).")
    enforce_quota(p)
    enforce_global_breaker()
    enforce_birth_lock(p.user_id, birth)                   # same one-native lock as the sync path
    store = get_store()
    if p.tier.monthly_tokens and store.credit_balance(p.user_id, p.tier)["available"] <= 0:
        raise HTTPException(402, "You're out of credits for this cycle, upgrade or add a top-up.")
    job_id = uuid.uuid4().hex
    store.job_put(job_id, {"job_id": job_id, "status": "queued", "owner": p.key})
    s = get_settings()
    if s.cloud_tasks_queue and s.worker_base_url:
        _enqueue_cloud_task(job_id, birth, p)              # production path
    else:
        background.add_task(_run_job, job_id, birth, p.tier.key, p.key, p.user_id)  # local path
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
    uid: str = ""


@app.post("/internal/run-reading")
def internal_run(payload: _TaskPayload, x_internal_token: Optional[str] = Header(default=None)):
    s = get_settings()
    if s.internal_token in _WEAK_INTERNAL_TOKENS:
        raise HTTPException(503, "Internal worker disabled: set a strong INTERNAL_TOKEN")
    if not _ct_eq(x_internal_token, s.internal_token):
        raise HTTPException(403, "forbidden")
    _run_job(payload.job_id, payload.birth, payload.tier, payload.key, payload.uid or payload.key)
    return {"status": "ok"}


@app.post("/internal/digest")
def internal_digest(x_internal_token: Optional[str] = Header(default=None)):
    """Compile a metrics digest (for a Cloud Scheduler cron). Logs it and, if
    DIGEST_WEBHOOK_URL is set, POSTs {text} to it (Slack/Zapier/email relay).
    Guarded by INTERNAL_TOKEN like the worker endpoint."""
    s = get_settings()
    if s.internal_token in _WEAK_INTERNAL_TOKENS:
        raise HTTPException(503, "Digest disabled: set a strong INTERNAL_TOKEN")
    if not _ct_eq(x_internal_token, s.internal_token):
        raise HTTPException(403, "forbidden")
    store = get_store()
    users = store.list_users()
    by_tier: dict = {}
    subs = 0
    for u in users:
        by_tier[u.get("tier", "free")] = by_tier.get(u.get("tier", "free"), 0) + 1
        subs += 1 if u.get("subscription_id") else 0
    pays = store.all_payments()
    captured = sum(int(p.get("amount_inr", 0)) for p in pays if p.get("status") == "captured")
    refunded = sum(int(p.get("amount_inr", 0)) for p in pays if p.get("status") == "refunded")
    mrr = sum(TIERS.get(u.get("tier", "free"), TIERS["free"]).price_inr_month
              for u in users if u.get("subscription_id"))
    tokens7 = sum(d["tokens"] for d in store.global_tokens_recent(7))
    today = datetime.now(timezone.utc).date()
    span = {(today - timedelta(d)).isoformat() for d in range(7)}
    signups7 = sum(1 for u in users if _to_date(u.get("created_at")) in span)
    paid = by_tier.get("basic", 0) + by_tier.get("pro", 0) + by_tier.get("enterprise", 0)
    text = "\n".join([
        f"Nakshatra digest — {today.isoformat()}",
        f"Users {len(users)} (paid {paid}, active subs {subs}) · signups 7d: {signups7}",
        "Tiers: " + ", ".join(f"{k} {by_tier.get(k, 0)}" for k in ("free", "basic", "pro", "enterprise")),
        f"MRR ₹{mrr:,} · net revenue ₹{captured - refunded:,}",
        f"Tokens 7d {tokens7:,} · today {store.global_tokens_today():,}",
    ])
    sent = False
    if s.digest_webhook_url:
        try:
            import urllib.request
            req = urllib.request.Request(
                s.digest_webhook_url, data=json.dumps({"text": text}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=15)
            sent = True
        except Exception:  # noqa: BLE001
            log.warning("digest webhook delivery failed")
    log.info("metrics digest:\n%s", text)
    return {"digest": text, "webhook_sent": sent}


def _enqueue_cloud_task(job_id: str, birth: BirthDetails, p: Principal):
    """Enqueue an HTTP task to Cloud Tasks that calls /internal/run-reading.

    Requires google-cloud-tasks. Kept import-local so the package runs without it.
    """
    from google.cloud import tasks_v2  # lazy
    s = get_settings()
    client = tasks_v2.CloudTasksClient()
    body = _TaskPayload(job_id=job_id, birth=birth, tier=p.tier.key, key=p.key, uid=p.user_id).model_dump_json().encode()
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
def _audit(admin: str, action: str, target: Optional[str] = None, **details) -> None:
    """Append an admin action to the audit log (best-effort; never blocks the action)."""
    try:
        get_store().audit_log({"ts": datetime.now(timezone.utc).isoformat(), "admin": admin,
                               "action": action, "target": target, "details": details})
    except Exception:  # noqa: BLE001
        log.warning("audit write failed action=%s", action)


@app.get("/admin/audit")
def admin_audit(limit: int = 100, _: None = Depends(require_admin)):
    return {"entries": get_store().list_audit(min(max(int(limit), 1), 500))}


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
def set_user_tier(req: UserTierRequest, admin: str = Depends(require_admin)):
    """Set a Firebase user's tier by uid (payment webhook / ops use this)."""
    if req.tier not in TIERS:
        raise HTTPException(400, f"Unknown tier; choose from {list(TIERS)}")
    store = get_store()
    store.upsert_user(req.uid, None)
    store.set_tier(req.uid, req.tier, source=req.source)
    _audit(admin, "set_tier", req.uid, tier=req.tier, source=req.source)
    return {"uid": req.uid, "tier": req.tier, "source": req.source}


# --------------------------------------------------------------------------- #
# beta cohort: grant a few users elevated access for feedback, tagged so they
# can be revoked en masse before switching to live Razorpay billing.
# --------------------------------------------------------------------------- #
class BetaGrantRequest(BaseModel):
    uid: str
    tier: str = "enterprise"


@app.post("/admin/beta/grant")
def beta_grant(req: BetaGrantRequest, admin: str = Depends(require_admin)):
    """Grant a user elevated access tagged tier_source='beta' (reversible later)."""
    if req.tier not in TIERS:
        raise HTTPException(400, f"Unknown tier; choose from {list(TIERS)}")
    store = get_store()
    store.upsert_user(req.uid, None)
    store.set_tier(req.uid, req.tier, source="beta")
    _audit(admin, "beta_grant", req.uid, tier=req.tier)
    return {"uid": req.uid, "tier": req.tier, "source": "beta"}


@app.get("/admin/beta")
def beta_list(_: None = Depends(require_admin)):
    """List the current beta-tagged users (for review before revoking)."""
    users = [u for u in get_store().list_users() if (u or {}).get("tier_source") == "beta"]
    return {"count": len(users),
            "users": [{"uid": u.get("uid") or u.get("id"), "email": u.get("email"),
                       "tier": u.get("tier")} for u in users]}


@app.post("/admin/beta/revoke")
def beta_revoke(admin: str = Depends(require_admin)):
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
    _audit(admin, "beta_revoke", count=len(revoked))
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
def codes_generate(req: CodeGenRequest, admin: str = Depends(require_admin)):
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
        # Codes are strictly SINGLE-USE: one redemption total, by one user, before
        # expiry. Once redeemed it is spent for everyone (the user-side guard also
        # keeps it spent for that user permanently). Generate `count` codes for
        # `count` people rather than one shared multi-use code.
        meta = {"kind": req.kind, "max_uses": 1, "uses": 0, "redeemed_by": [],
                "active": True, "expires_at": exp, "created_at": now.isoformat()}
        if req.kind == "beta":
            meta["tier"] = req.tier
        else:
            meta["discount_pct"] = req.discount_pct
        store.code_create(hash_code(code), meta)
        plaintext.append(code)
    _audit(admin, "codes_generate", kind=req.kind, count=len(plaintext),
           tier=req.tier if req.kind == "beta" else None,
           discount_pct=req.discount_pct if req.kind == "discount" else None)
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
    ch = hash_code(req.code)
    # Permanent per-user guard: a code is spent for a user forever once redeemed,
    # independent of the code's own expiry/uses (survives a code regen/reset too).
    if ch in ((store.get_user(p.user_id) or {}).get("redeemed_codes") or []):
        raise HTTPException(400, "You have already redeemed this code.")
    res = store.code_redeem(ch, p.user_id)
    if not res.get("ok"):
        raise HTTPException(400, res.get("reason") or "Invalid code.")
    store.add_redeemed_code(p.user_id, ch)
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
def admin_reset_birth(uid: str, admin: str = Depends(require_admin)):
    """Clear a user's saved birth lock (support: typo in DOB/place, or a genuine
    re-assignment). The next birth-based call re-locks to the new person."""
    get_store().clear_birth_lock(uid)
    _audit(admin, "reset_birth", uid)
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


@app.post("/v1/birth-change-request/dismiss")
def dismiss_change_notice(p: Principal = Depends(require_principal)):
    """Acknowledge the resolved change-request banner so it stops showing."""
    store = get_store()
    latest = store.user_latest_change_request(p.user_id)
    if latest and latest.get("status") in ("approved", "rejected"):
        store.update_change_request(latest["id"], {"acked": True})
    return {"ok": True}


@app.get("/admin/birth-change-requests")
def admin_list_change_requests(_: None = Depends(require_admin)):
    return {"requests": get_store().list_change_requests(status="pending")}


def _resolve_change_request(rid: str, decision: str, admin: str) -> dict:
    store = get_store()
    r = store.get_change_request(rid)
    if not r:
        raise HTTPException(404, "Unknown request")
    if r.get("status") != "pending":
        raise HTTPException(409, f"Request already {r.get('status')}.")
    if decision == "approved":
        store.clear_birth_lock(r["uid"])     # unlock so the user can re-enter details
    store.update_change_request(rid, {"status": decision, "acked": False,
                                      "resolved_at": datetime.now(timezone.utc).isoformat()})
    _audit(admin, f"birth_change_{decision}", r["uid"])
    return {"id": rid, "uid": r["uid"], "status": decision}


@app.post("/admin/birth-change-requests/{rid}/approve")
def admin_approve_change(rid: str, admin: str = Depends(require_admin)):
    return _resolve_change_request(rid, "approved", admin)


@app.post("/admin/birth-change-requests/{rid}/reject")
def admin_reject_change(rid: str, admin: str = Depends(require_admin)):
    return _resolve_change_request(rid, "rejected", admin)


@app.post("/admin/codes/{code_id}/deactivate")
def codes_deactivate(code_id: str, admin: str = Depends(require_admin)):
    if not get_store().code_set_active(code_id, False):
        raise HTTPException(404, "Unknown code id")
    _audit(admin, "code_deactivate", code_id[:10])
    return {"id": code_id, "active": False}


@app.post("/admin/codes/{code_id}/reactivate")
def codes_reactivate(code_id: str, admin: str = Depends(require_admin)):
    if not get_store().code_set_active(code_id, True):
        raise HTTPException(404, "Unknown code id")
    _audit(admin, "code_reactivate", code_id[:10])
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
def admin_approve_refund(rid: str, admin: str = Depends(require_admin)):
    r = get_store().refund_request_get(rid)
    if not r:
        raise HTTPException(404, "Unknown refund request")
    if r.get("status") != "pending":
        raise HTTPException(409, f"Request already {r.get('status')}")
    result = _process_refund(r["payment_id"])
    get_store().refund_request_set_status(rid, "approved")
    _audit(admin, "refund_approved", r.get("uid"), payment_id=r.get("payment_id"))
    return {"status": "approved", "refund": result}


@app.post("/admin/refunds/{rid}/reject")
def admin_reject_refund(rid: str, admin: str = Depends(require_admin)):
    r = get_store().refund_request_get(rid)
    if not r:
        raise HTTPException(404, "Unknown refund request")
    get_store().refund_request_set_status(rid, "rejected")
    _audit(admin, "refund_rejected", r.get("uid"), payment_id=r.get("payment_id"))
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
        jb = int(u.get("jailbreak_count") or 0)
        if jb >= s.anomaly_jailbreak_flag:
            reasons.append(f"{jb} jailbreak attempts")
        if reasons:
            flagged.append({"uid": uid, "reasons": reasons, "last_ip": ip,
                            "last_seen": _iso(a.get("last_seen")), "tier": u.get("tier"),
                            "banned": bool(store.get_ban(uid))})
    return flagged


def _fraud_scan(persist: bool, autoban: bool) -> dict:
    """Score EVERY user with the full risk model (incl. cross-user signals).
    persist -> write each user's risk band; autoban -> suspend users at/over the
    auto-ban score. Returns a summary + the flagged (non-ok) users sorted by score."""
    s = get_settings()
    store = get_store()
    users = store.list_users()
    refund_counts: dict = {}
    for r in store.list_refund_requests():
        refund_counts[r.get("uid")] = refund_counts.get(r.get("uid"), 0) + 1
    ip_map: dict = {}
    acts: dict = {}
    for u in users:
        a = store.get_activity(u["uid"]) or {}
        acts[u["uid"]] = a
        if a.get("last_ip"):
            ip_map.setdefault(a["last_ip"], []).append(u["uid"])

    flagged, watch, high, banned = [], 0, 0, 0
    for u in users:
        uid = u["uid"]
        a = acts.get(uid, {})
        usage = store.usage_today(uid) or {}
        ctx = {
            "refunds": refund_counts.get(uid, 0),
            "tokens_today": int(usage.get("tokens_in", 0)) + int(usage.get("tokens_out", 0)),
            "ip_accounts": len(ip_map.get(a.get("last_ip"), [])) if a.get("last_ip") else 0,
        }
        risk = fraud.compute_risk(u, ctx, s)
        if persist:
            try:
                store.set_risk(uid, {**risk, "ts": _iso(datetime.now(timezone.utc))})
            except Exception:  # noqa: BLE001
                pass
        if autoban and s.fraud_autoban_score and risk["score"] >= s.fraud_autoban_score and not store.get_ban(uid):
            try:
                # a TEMPORARY ban with a real expiry so it lifts itself (is_banned
                # auto-clears once `until` passes); the risk score decays in parallel.
                until = datetime.now(timezone.utc) + timedelta(days=s.fraud_autoban_days)
                store.set_ban(uid, "temporary", f"auto: fraud risk score {risk['score']}",
                              until=until, by="fraud-monitor")
                _audit("fraud-monitor", "auto_ban", uid, score=risk["score"], days=s.fraud_autoban_days)
                banned += 1
            except Exception:  # noqa: BLE001
                pass
        if risk["band"] != "ok":
            high += risk["band"] == "high"
            watch += risk["band"] == "watch"
            flagged.append({"uid": uid, "email": u.get("email"), "tier": u.get("tier", "free"),
                            "score": risk["score"], "band": risk["band"], "signals": risk["signals"],
                            "last_ip": a.get("last_ip"), "banned": bool(store.get_ban(uid))})
    flagged.sort(key=lambda x: x["score"], reverse=True)
    return {"scanned": len(users), "watch": watch, "high": high, "auto_banned": banned, "flagged": flagged}


@app.post("/internal/fraud-scan")
def internal_fraud_scan(x_internal_token: Optional[str] = Header(default=None)):
    """Continuous fraud monitoring (a Cloud Scheduler cron). Scores every user,
    persists their risk band (drives the warning banner), and auto-suspends the
    worst. INTERNAL_TOKEN-guarded like the other internal jobs."""
    s = get_settings()
    if s.internal_token in _WEAK_INTERNAL_TOKENS:
        raise HTTPException(503, "Fraud scan disabled: set a strong INTERNAL_TOKEN")
    if not _ct_eq(x_internal_token, s.internal_token):
        raise HTTPException(403, "forbidden")
    res = _fraud_scan(persist=True, autoban=True)
    log.info("fraud-scan: scanned=%s watch=%s high=%s auto_banned=%s",
             res["scanned"], res["watch"], res["high"], res["auto_banned"])
    return {k: v for k, v in res.items() if k != "flagged"} | {"flagged_count": len(res["flagged"])}


@app.get("/admin/fraud")
def admin_fraud(_: None = Depends(require_admin)):
    """Live fraud-risk view for the dashboard (scored on read, not auto-banning)."""
    return _fraud_scan(persist=False, autoban=False)


@app.get("/admin/ping")
def admin_ping(_: None = Depends(require_admin)):
    return {"admin": True}


@app.get("/admin/anomalies")
def admin_anomalies(_: None = Depends(require_admin)):
    return {"flagged": _scan_anomalies()}


@app.get("/admin/feedback")
def admin_feedback(_: None = Depends(require_admin)):
    """User feedback collected via the in-app feedback button (newest first)."""
    rows = get_store().list_feedback(300)
    return {"count": len(rows), "feedback": rows}


@app.get("/admin/grievances")
def admin_grievances(_: None = Depends(require_admin)):
    """Data-privacy grievances filed by users (DPDP s13), newest first."""
    rows = get_store().list_grievances(300)
    return {"count": len(rows), "grievances": rows}


class BreachIn(BaseModel):
    # Fields mirror DPDP Rules 2025, Rule 7 (intimation of personal data breach):
    # nature/extent/timing/location, likely impact, consequences to principals, the
    # mitigation in place, the safety steps a user can take, and a responder contact.
    description: str = Field(..., min_length=5, max_length=8000)   # nature & extent
    severity: Literal["low", "medium", "high", "critical"] = "high"
    affected_count: Optional[int] = Field(None, ge=0)
    occurred_at: Optional[str] = Field(None, max_length=40)        # timing of occurrence
    location: Optional[str] = Field(None, max_length=200)          # where it occurred
    discovered_at: Optional[str] = Field(None, max_length=40)      # when we became aware
    likely_impact: Optional[str] = Field(None, max_length=4000)
    consequences: Optional[str] = Field(None, max_length=4000)     # consequences to principals
    mitigation: Optional[str] = Field(None, max_length=4000)       # measures implemented
    safety_measures: Optional[str] = Field(None, max_length=4000)  # what the user can do
    responder_contact: Optional[str] = Field(None, max_length=200)
    notified_board: bool = False
    notified_principals: bool = False


@app.post("/admin/breach")
def admin_record_breach(req: BreachIn, admin: str = Depends(require_admin)):
    """Record a personal-data-breach incident (DPDP s8(6) / GDPR Art 33-34). This is the
    auditable register; see docs/INCIDENT_RESPONSE.md for the notification runbook (Board +
    affected Data Principals, GDPR 72-hour clock)."""
    entry = {**req.model_dump(), "ts": datetime.now(timezone.utc).isoformat(), "by": admin}
    get_store().add_breach(entry)
    _audit(admin, "record_breach", "", severity=req.severity, affected=req.affected_count)
    return {"ok": True, "breach": entry}


@app.get("/admin/breaches")
def admin_breaches(_: None = Depends(require_admin)):
    """The breach register (newest first)."""
    rows = get_store().list_breaches(300)
    return {"count": len(rows), "breaches": rows}


@app.get("/admin/overview")
def admin_overview(_: None = Depends(require_admin)):
    """Rich platform analytics: tier mix, active users, revenue/MRR, codes, token
    trend, pending queues. One payload that drives the analytics dashboard."""
    store = get_store()
    now = datetime.now(timezone.utc)
    users = store.list_users()
    by_tier = {"free": 0, "basic": 0, "pro": 0, "enterprise": 0}
    locked = subs = active7 = active30 = 0
    for u in users:
        by_tier[u.get("tier", "free")] = by_tier.get(u.get("tier", "free"), 0) + 1
        if u.get("birth_lock"):
            locked += 1
        if u.get("subscription_id"):
            subs += 1
        ls = (store.get_activity(u.get("uid")) or {}).get("last_seen")
        if ls:
            try:
                dt = ls if isinstance(ls, datetime) else datetime.fromisoformat(str(ls).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age = (now - dt).days
                active7 += age <= 7
                active30 += age <= 30
            except Exception:  # noqa: BLE001
                pass
    pays = store.all_payments()
    captured = sum(int(p.get("amount_inr", 0)) for p in pays if p.get("status") == "captured")
    refunded = sum(int(p.get("amount_inr", 0)) for p in pays if p.get("status") == "refunded")
    mrr = sum(TIERS.get(u.get("tier", "free"), TIERS["free"]).price_inr_month
              for u in users if u.get("subscription_id"))
    codes = store.list_codes()
    by_kind: dict = {}
    for c in codes:
        by_kind[c.get("kind", "?")] = by_kind.get(c.get("kind", "?"), 0) + 1
    paid = by_tier.get("basic", 0) + by_tier.get("pro", 0) + by_tier.get("enterprise", 0)
    jailbreakers = sum(1 for u in users if int(u.get("jailbreak_count") or 0) > 0)
    return {
        "users": {"total": len(users), "by_tier": by_tier, "active_7d": active7,
                  "active_30d": active30, "birth_locked": locked, "with_subscription": subs,
                  "paid": paid, "conversion_pct": round(100 * paid / max(len(users), 1), 1),
                  "jailbreakers": jailbreakers},
        "revenue": {"captured_inr": captured, "refunded_inr": refunded,
                    "net_inr": captured - refunded, "mrr_inr": mrr},
        "codes": {"total": len(codes), "redemptions": sum(int(c.get("uses", 0)) for c in codes),
                  "active": sum(1 for c in codes if c.get("active") and c.get("uses", 0) < c.get("max_uses", 1)),
                  "by_kind": by_kind},
        "requests": {"refunds_pending": len(store.list_refund_requests("pending")),
                     "birth_changes_pending": len(store.list_change_requests("pending"))},
        "tokens": {"today": store.global_tokens_today(), "series": store.global_tokens_recent(14)},
        "platform_cost": pricing.monthly_platform_cost(max(len(users), 1)),
    }


def _to_date(v) -> Optional[str]:
    """Best-effort YYYY-MM-DD from a datetime, Firestore Timestamp, or ISO string."""
    if v is None:
        return None
    try:
        if hasattr(v, "isoformat"):
            return v.isoformat()[:10]
        return str(v)[:10]
    except Exception:  # noqa: BLE001
        return None


@app.get("/admin/analytics")
def admin_analytics(days: int = 30, _: None = Depends(require_admin)):
    """Time-series + funnel + top consumers. `days` selects the window (1-365)."""
    days = min(max(int(days), 1), 365)
    store = get_store()
    today = datetime.now(timezone.utc).date()
    span = [(today - timedelta(d)).isoformat() for d in range(days - 1, -1, -1)]
    span_set = set(span)
    users = store.list_users()

    signups = {d: 0 for d in span}
    for u in users:
        d = _to_date(u.get("created_at"))
        if d in span_set:
            signups[d] += 1

    revenue = {d: 0 for d in span}
    for p_ in store.all_payments():
        if p_.get("status") == "captured":
            d = _to_date(p_.get("ts"))
            if d in span_set:
                revenue[d] += int(p_.get("amount_inr", 0))

    # funnel from available signals
    activated = sum(1 for u in users if u.get("birth_lock"))
    redeemed = sum(1 for u in users if u.get("tier_source") in ("beta",) or int(u.get("discount_pct") or 0) > 0)
    paid = sum(1 for u in users if u.get("subscription_id") or u.get("tier_source") == "payment")
    total = len(users)

    top = sorted(users, key=lambda u: int(u.get("tokens_total") or 0), reverse=True)[:10]
    top_consumers = [{"uid": u.get("uid"), "email": u.get("email"), "tier": u.get("tier"),
                      "tokens_total": int(u.get("tokens_total") or 0)} for u in top if int(u.get("tokens_total") or 0) > 0]

    return {
        "days": days,
        "signups_by_day": [{"date": d, "count": signups[d]} for d in span],
        "revenue_by_day": [{"date": d, "inr": revenue[d]} for d in span],
        "funnel": [
            {"stage": "Signed up", "count": total},
            {"stage": "Cast a reading", "count": activated},
            {"stage": "Redeemed a code", "count": redeemed},
            {"stage": "Paid", "count": paid},
        ],
        "top_consumers": top_consumers,
    }


@app.get("/admin/users")
def admin_users(_: None = Depends(require_admin)):
    """All users with the key analytics fields, for the clickable users table."""
    store = get_store()
    out = []
    for u in store.list_users():
        uid = u.get("uid")
        a = store.get_activity(uid) or {}
        usage = store.usage_today(uid) or {}
        out.append({
            "uid": uid, "email": u.get("email"), "tier": u.get("tier", "free"),
            "tier_source": u.get("tier_source"), "banned": bool(store.get_ban(uid)),
            "last_ip": a.get("last_ip"), "last_seen": _iso(a.get("last_seen")),
            "tokens_today": int(usage.get("tokens_in", 0)) + int(usage.get("tokens_out", 0)),
            "has_subscription": bool(u.get("subscription_id")),
            "discount_pct": int(u.get("discount_pct") or 0),
            "birth_locked": bool(u.get("birth_lock")),
            "jailbreak_count": int(u.get("jailbreak_count") or 0),
        })
    out.sort(key=lambda x: x.get("last_seen") or "", reverse=True)
    return {"count": len(out), "users": out}


@app.get("/admin/users/{uid}")
def admin_user_detail(uid: str, _: None = Depends(require_admin)):
    """Full profile + analytics for one user (drill-down from the users table)."""
    store = get_store()
    u = store.get_user(uid)
    if not u:
        raise HTTPException(404, "Unknown user")
    tier = TIERS.get(u.get("tier", "free"), TIERS["free"])
    a = store.get_activity(uid) or {}
    usage = store.usage_today(uid) or {}
    return {
        "uid": uid, "email": u.get("email"), "tier": u.get("tier", "free"),
        "tier_source": u.get("tier_source"), "discount_pct": int(u.get("discount_pct") or 0),
        "has_subscription": bool(u.get("subscription_id")), "subscription_id": u.get("subscription_id"),
        "birth_lock": u.get("birth_lock"),
        "balance": store.credit_balance(uid, tier),
        "tokens_today": int(usage.get("tokens_in", 0)) + int(usage.get("tokens_out", 0)),
        "activity": {"last_ip": a.get("last_ip"), "last_seen": _iso(a.get("last_seen")),
                     "count": a.get("count")},
        "ban": store.get_ban(uid),
        "jailbreak_count": int(u.get("jailbreak_count") or 0),
        "malicious_count": int(u.get("malicious_count") or 0),
        "jailbreak_last": u.get("jailbreak_last"),
        "jailbreaks": store.list_jailbreaks(uid, 20),
        "risk": fraud.compute_risk(u, {"tokens_today": int(usage.get("tokens_in", 0)) + int(usage.get("tokens_out", 0))}, get_settings()),
        "payments": [p for p in store.all_payments() if p.get("uid") == uid],
        "refunds": [r for r in store.list_refund_requests() if r.get("uid") == uid],
        "audit": [e for e in store.list_audit(500) if e.get("target") == uid][:30],
    }


TEST_USER_PREFIX = "qa_"   # convention: every QA/smoke account uid starts with this


class DeleteUserReq(BaseModel):
    confirm: bool = False   # real accounts (with an email) require an explicit confirm


def _is_real_account(uid: str, user: dict | None) -> bool:
    """A real signup = has an email AND the uid is not a qa_/test account."""
    email = (user or {}).get("email") or ""
    return ("@" in email) and not uid.startswith(TEST_USER_PREFIX)


@app.post("/admin/users/{uid}/delete")
def admin_delete_user(uid: str, req: Optional[DeleteUserReq] = None, admin: str = Depends(require_admin)):
    """Delete a user (profile, keys, chats) and clear any ban. SAFEGUARD: a real
    account (has an email, uid not prefixed qa_) can't be deleted unless confirm=true,
    so bulk/accidental cleanup can never wipe a real signup (e.g. a beta tester)."""
    store = get_store()
    user = store.get_user(uid)
    if _is_real_account(uid, user) and not (req and req.confirm):
        raise HTTPException(409, "This looks like a real account (has an email). "
                                 "Pass confirm=true to delete it.")
    store.clear_ban(uid)
    res = store.delete_user(uid)
    _audit(admin, "delete_user", uid)
    return {"uid": uid, "deleted": True, **(res or {})}


@app.post("/admin/test-users/purge")
def purge_test_users(admin: str = Depends(require_admin)):
    """Safely delete ONLY QA/test accounts (uid prefixed `qa_`). Never touches real
    signups, so cleanup can't hit a beta tester."""
    store = get_store()
    deleted = []
    for u in store.list_users():
        uid = u.get("uid") or ""
        if uid.startswith(TEST_USER_PREFIX):
            store.clear_ban(uid)
            store.delete_user(uid)
            deleted.append(uid)
    _audit(admin, "purge_test_users", count=len(deleted))
    return {"deleted": deleted, "count": len(deleted)}


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
