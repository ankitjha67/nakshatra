"""Control plane: tiers, store, auth, quota.

Everything an end user is *entitled* to is defined in TIERS. The store keeps API
keys, user records (Firebase-authenticated), usage counters, the reading cache,
and async jobs. The memory backend boots with dev keys so you can try the API
immediately; the Firestore backend persists all of it for production.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import Header, HTTPException

from . import credits
from .config import get_settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _chat_expire_at(now: datetime) -> Optional[datetime]:
    """Expiry stamp for chat messages when a retention window is configured
    (drives a Firestore TTL policy). None = keep indefinitely."""
    days = get_settings().chat_retention_days
    return now + timedelta(days=days) if days and days > 0 else None


# --------------------------------------------------------------------------- #
# tiers
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Tier:
    key: str
    label: str
    price_inr_month: int
    sections: frozenset[str]        # which reading sections are unlocked
    llm: bool                       # is LLM rendering included
    daily_limit: int                # requests/day
    per_minute: int                 # burst limit
    allow_async: bool = False
    api_access: bool = False        # programmatic/B2B
    cache: bool = True
    monthly_tokens: int = 0         # chat token grant refreshed each cycle (CREDIT_LEDGER.md)

    @property
    def reading_allowed(self) -> bool:
        return self.llm and bool(self.sections)


ALL_SECTIONS = frozenset({
    "essence", "mind", "relationships", "career", "wealth", "family", "health",
    "timing", "fortune", "spirit", "strengths", "kp", "panchang", "alerts",
    "numbers", "remedies",
})

# Pro+ also unlock the report-scoped "yearly" (Varshphal) section. It's kept OUT of
# ALL_SECTIONS on purpose so maha_kundali (= ALL_SECTIONS) never renders it — only a
# report_type="yearly" request, whose REPORT_TYPES set includes "yearly", does.
_PRO_SECTIONS = ALL_SECTIONS | frozenset({"yearly"})

TIERS: dict[str, Tier] = {
    "free":  Tier("free",  "Free",        0,    frozenset(),                       False, 5,    3, monthly_tokens=0),
    "basic": Tier("basic", "Basic",       299,  frozenset({"essence", "mind", "relationships", "career", "timing"}), True, 50, 10, monthly_tokens=50_000),
    "pro":   Tier("pro",   "Pro",         999,  _PRO_SECTIONS,                     True,  500,  30, allow_async=True, monthly_tokens=500_000),
    "enterprise": Tier("enterprise", "API / Business", 4999, _PRO_SECTIONS,        True,  10000, 120, allow_async=True, api_access=True, monthly_tokens=5_000_000),
}


def tier_catalog() -> list[dict]:
    return [{
        "key": t.key, "label": t.label, "price_inr_month": t.price_inr_month,
        "reading": t.reading_allowed, "sections": sorted(t.sections),
        "daily_limit": t.daily_limit, "per_minute": t.per_minute,
        "async": t.allow_async, "api_access": t.api_access,
        "monthly_tokens": t.monthly_tokens,
    } for t in TIERS.values()]


# --------------------------------------------------------------------------- #
# report types (same birth-details flow; differ only by which sections render)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ReportType:
    key: str
    label: str
    min_tier: str               # tab is visible from this tier up (advisory; gating is by section ∩)
    sections: frozenset[str]    # the report's full section-set, before tier intersection


# "yearly" carries a (Phase 3) yearly section that isn't in ALL_SECTIONS yet, so it
# is dropped by the tier intersection until then — the rest of its set still renders.
REPORT_TYPES: dict[str, ReportType] = {
    "natal":        ReportType("natal", "Natal", "basic",
                               frozenset({"essence", "mind", "relationships", "career", "timing", "spirit"})),
    "maha_kundali": ReportType("maha_kundali", "Maha-Kundali", "pro", ALL_SECTIONS),
    "yearly":       ReportType("yearly", "Yearly (Varshphal)", "pro",
                               frozenset({"yearly", "timing", "fortune", "alerts"})),
}
DEFAULT_REPORT_TYPE = "maha_kundali"


def report_sections(report_type: str) -> frozenset[str]:
    rt = REPORT_TYPES.get(report_type) or REPORT_TYPES[DEFAULT_REPORT_TYPE]
    return rt.sections


def report_type_catalog() -> list[dict]:
    return [{"key": rt.key, "label": rt.label, "min_tier": rt.min_tier,
             "sections": sorted(rt.sections)} for rt in REPORT_TYPES.values()]


# --------------------------------------------------------------------------- #
# credit ledger — doc <-> Balance mapping + the shared mutation planner
# --------------------------------------------------------------------------- #
def _as_dt(v, fallback: datetime) -> datetime:
    """Coerce a stored cycle timestamp to a tz-aware datetime. Firestore returns
    a DatetimeWithNanoseconds (a datetime); accept ISO strings too for safety."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return fallback
    return fallback


def _balance_from_doc(doc: Optional[dict], now: datetime) -> Optional[credits.Balance]:
    """Reconstruct a Balance from a stored users/{uid} doc, or None if the
    credit fields have never been initialised."""
    if not doc or "grant_balance" not in doc:
        return None
    return credits.Balance(
        tier=doc.get("tier", "free"),
        grant_balance=int(doc.get("grant_balance", 0)),
        topup_balance=int(doc.get("topup_balance", 0)),
        monthly_tokens=int(doc.get("monthly_tokens", 0)),
        cycle_start=_as_dt(doc.get("cycle_start"), now),
        cycle_end=_as_dt(doc.get("cycle_end"), now),
        daily_tokens_used=int(doc.get("daily_tokens_used", 0)),
        daily_date=doc.get("daily_date", ""),
    )


def _balance_to_doc(bal: credits.Balance, now: datetime) -> dict:
    # cycle_start/cycle_end/updated_at are tz-aware datetimes → Firestore Timestamps.
    return {
        "tier": bal.tier, "grant_balance": bal.grant_balance, "topup_balance": bal.topup_balance,
        "monthly_tokens": bal.monthly_tokens, "cycle_start": bal.cycle_start, "cycle_end": bal.cycle_end,
        "daily_tokens_used": bal.daily_tokens_used, "daily_date": bal.daily_date,
        "updated_at": now,
    }


def _plan(bal: Optional[credits.Balance], tier: "Tier", op: str, now: datetime,
          *, cost: int = 0, tokens: int = 0, reason: str = "", ref: Optional[str] = None
          ) -> tuple[credits.Balance, list[dict]]:
    """Pure: given the current balance (or None to initialise) and a tier, apply
    the lazy resets and then the requested op. Returns the new balance and the
    ledger entries to append. Stores call this inside their atomic boundary."""
    entries: list[dict] = []
    if bal is None:
        bal, opening = credits.new_balance(tier.key, tier.monthly_tokens, now)
        entries.append(opening)
    else:
        bal, resets = credits.apply_resets(bal, tier.key, tier.monthly_tokens, now)
        entries += resets
    if op == "debit":
        bal, e = credits.debit(bal, cost, reason or "chat turn", ref, now); entries.append(e)
    elif op == "topup":
        bal, e = credits.topup(bal, tokens, reason or "top-up", ref, now); entries.append(e)
    elif op == "grant":
        bal, e = credits.grant(bal, tier.monthly_tokens, reason or "monthly grant", now); entries.append(e)
    elif op == "refund":
        bal, e = credits.refund(bal, tokens, reason or "refund", ref, now); entries.append(e)
    # op == "read": resets/init only
    return bal, entries


# --------------------------------------------------------------------------- #
# store
# --------------------------------------------------------------------------- #
@dataclass
class ApiKeyRecord:
    key: str
    user_id: str
    tier: str
    disabled: bool = False


class Store:
    # api keys (programmatic / B2B)
    def get_key(self, key: str) -> Optional[ApiKeyRecord]: ...
    def create_key(self, key: str, user_id: str, tier: str) -> ApiKeyRecord: ...
    def set_tier(self, user_id: str, tier: str) -> None: ...
    # users (Firebase-authenticated; keyed by uid)
    def get_user(self, uid: str) -> Optional[dict]: ...
    def upsert_user(self, uid: str, email: Optional[str], tier: Optional[str] = None) -> dict: ...
    # usage + rate
    def hit_rate(self, key: str, per_minute: int) -> bool: ...      # True if allowed
    def usage_today(self, key: str) -> dict: ...
    def record(self, key: str, tokens_in: int, tokens_out: int, reading: bool) -> None: ...
    # reading cache
    def cache_get(self, ck: str) -> Optional[dict]: ...
    def cache_put(self, ck: str, value: dict) -> None: ...
    # jobs
    def job_put(self, job_id: str, value: dict) -> None: ...
    def job_get(self, job_id: str) -> Optional[dict]: ...
    # credit ledger (money path — server-side + atomic; see docs/CREDIT_LEDGER.md)
    def credit_balance(self, uid: str, tier: "Tier", now: Optional[datetime] = None) -> dict: ...
    def credit_debit(self, uid: str, tier: "Tier", cost: int, reason: str = "chat turn",
                     ref: Optional[str] = None, now: Optional[datetime] = None) -> dict: ...
    def credit_topup(self, uid: str, tier: "Tier", tokens: int, reason: str = "top-up",
                     ref: Optional[str] = None, now: Optional[datetime] = None) -> dict: ...
    def credit_grant(self, uid: str, tier: "Tier", reason: str = "monthly grant",
                     now: Optional[datetime] = None) -> dict: ...
    def credit_refund(self, uid: str, tier: "Tier", tokens: int, reason: str = "refund",
                      ref: Optional[str] = None, now: Optional[datetime] = None) -> dict: ...
    def credit_ledger(self, uid: str, limit: int = 20) -> list: ...
    # payment records + refund requests (reconciliation / "did they actually pay")
    def record_payment(self, payment_id: str, data: dict) -> None: ...
    def get_payment(self, payment_id: str) -> Optional[dict]: ...
    def set_payment_status(self, payment_id: str, status: str) -> None: ...
    def list_payments(self, uid: str) -> list: ...
    def refund_request_create(self, req_id: str, data: dict) -> None: ...
    def refund_request_get(self, req_id: str) -> Optional[dict]: ...
    def refund_request_set_status(self, req_id: str, status: str) -> None: ...
    def list_refund_requests(self, status: Optional[str] = None) -> list: ...
    # chat persistence (NOT the money path — best-effort)
    def chat_save_turn(self, uid: str, chat_id: str, chart_hash: str, user_text: str,
                       assistant_text: str, tokens: int, msg_id: str,
                       now: Optional[datetime] = None) -> str: ...
    # payment idempotency — True if this id is newly recorded, False if already seen
    def mark_payment_processed(self, payment_id: str) -> bool: ...
    # platform-wide token spend today (for the global cost breaker)
    def global_tokens_today(self) -> int: ...
    # GDPR data-subject rights
    def export_user(self, uid: str) -> dict: ...
    def delete_user(self, uid: str) -> dict: ...


@dataclass
class MemoryStore(Store):
    keys: dict[str, ApiKeyRecord] = field(default_factory=dict)
    users: dict[str, dict] = field(default_factory=dict)
    usage: dict[tuple[str, str], dict] = field(default_factory=dict)
    rate: dict[str, list[float]] = field(default_factory=dict)
    reading_cache: dict[str, dict] = field(default_factory=dict)
    jobs: dict[str, dict] = field(default_factory=dict)
    ledger_entries: dict[str, list] = field(default_factory=dict)
    chats: dict[str, dict] = field(default_factory=dict)
    processed_payments: set = field(default_factory=set)
    global_usage: dict = field(default_factory=dict)   # date -> total tokens
    payments: dict = field(default_factory=dict)        # payment_id -> record
    refund_requests: dict = field(default_factory=dict)  # req_id -> record

    def get_key(self, key):
        return self.keys.get(key)

    def create_key(self, key, user_id, tier):
        rec = ApiKeyRecord(key=key, user_id=user_id, tier=tier)
        self.keys[key] = rec
        return rec

    def set_tier(self, user_id, tier):
        for r in self.keys.values():
            if r.user_id == user_id:
                r.tier = tier
        if user_id in self.users:
            self.users[user_id]["tier"] = tier

    def get_user(self, uid):
        return self.users.get(uid)

    def upsert_user(self, uid, email, tier=None):
        u = self.users.get(uid)
        if u:
            if email and u.get("email") != email:
                u["email"] = email
            return u
        u = {"email": email or "", "tier": tier or "free"}
        self.users[uid] = u
        return u

    def hit_rate(self, key, per_minute):
        now = time.time()
        bucket = [t for t in self.rate.get(key, []) if now - t < 60]
        if len(bucket) >= per_minute:
            self.rate[key] = bucket
            return False
        bucket.append(now)
        self.rate[key] = bucket
        return True

    def usage_today(self, key):
        return self.usage.get((key, date.today().isoformat()),
                              {"calls": 0, "readings": 0, "tokens_in": 0, "tokens_out": 0})

    def record(self, key, tokens_in, tokens_out, reading):
        today = date.today().isoformat()
        k = (key, today)
        u = self.usage.get(k, {"calls": 0, "readings": 0, "tokens_in": 0, "tokens_out": 0})
        u["calls"] += 1
        u["readings"] += 1 if reading else 0
        u["tokens_in"] += tokens_in
        u["tokens_out"] += tokens_out
        self.usage[k] = u
        self.global_usage[today] = self.global_usage.get(today, 0) + int(tokens_in) + int(tokens_out)

    def global_tokens_today(self):
        return int(self.global_usage.get(date.today().isoformat(), 0))

    def cache_get(self, ck):
        return self.reading_cache.get(ck)

    def cache_put(self, ck, value):
        self.reading_cache[ck] = value

    def job_put(self, job_id, value):
        self.jobs[job_id] = value

    def job_get(self, job_id):
        return self.jobs.get(job_id)

    # --- credit ledger (single-threaded → atomic by construction) ---
    def _credit_apply(self, uid, tier, op, *, now=None, **kw) -> credits.Balance:
        now = now or _now()
        doc = self.users.get(uid) or {}
        bal, entries = _plan(_balance_from_doc(doc, now), tier, op, now, **kw)
        self.users[uid] = {**doc, **_balance_to_doc(bal, now)}
        self.ledger_entries.setdefault(uid, []).extend(entries)
        return bal

    def credit_balance(self, uid, tier, now=None):
        return self._credit_apply(uid, tier, "read", now=now).as_public()

    def credit_debit(self, uid, tier, cost, reason="chat turn", ref=None, now=None):
        return self._credit_apply(uid, tier, "debit", now=now, cost=cost, reason=reason, ref=ref).as_public()

    def credit_topup(self, uid, tier, tokens, reason="top-up", ref=None, now=None):
        return self._credit_apply(uid, tier, "topup", now=now, tokens=tokens, reason=reason, ref=ref).as_public()

    def credit_grant(self, uid, tier, reason="monthly grant", now=None):
        return self._credit_apply(uid, tier, "grant", now=now, reason=reason).as_public()

    def credit_refund(self, uid, tier, tokens, reason="refund", ref=None, now=None):
        return self._credit_apply(uid, tier, "refund", now=now, tokens=tokens, reason=reason, ref=ref).as_public()

    def credit_ledger(self, uid, limit=20):
        return list(reversed(self.ledger_entries.get(uid, [])))[:limit]

    # --- payment records + refund requests ---
    def record_payment(self, payment_id, data):
        self.payments[payment_id] = {**data, "payment_id": payment_id}

    def get_payment(self, payment_id):
        return self.payments.get(payment_id)

    def set_payment_status(self, payment_id, status):
        if payment_id in self.payments:
            self.payments[payment_id]["status"] = status

    def list_payments(self, uid):
        return [p for p in self.payments.values() if p.get("uid") == uid]

    def refund_request_create(self, req_id, data):
        self.refund_requests[req_id] = {**data, "id": req_id}

    def refund_request_get(self, req_id):
        return self.refund_requests.get(req_id)

    def refund_request_set_status(self, req_id, status):
        if req_id in self.refund_requests:
            self.refund_requests[req_id]["status"] = status

    def list_refund_requests(self, status=None):
        return [r for r in self.refund_requests.values() if status is None or r.get("status") == status]

    def chat_save_turn(self, uid, chat_id, chart_hash, user_text, assistant_text, tokens, msg_id, now=None):
        now = now or _now()
        exp = _chat_expire_at(now)
        c = self.chats.setdefault(uid, {}).setdefault(
            chat_id, {"chart_hash": chart_hash, "created_at": now, "messages": []})
        c["messages"].append({"role": "user", "text": user_text, "tokens": None, "ts": now, "expireAt": exp})
        c["messages"].append({"role": "assistant", "text": assistant_text,
                              "tokens": int(tokens), "ts": now, "id": msg_id, "expireAt": exp})
        return chat_id

    def export_user(self, uid):
        return {"user": self.users.get(uid), "ledger": list(self.ledger_entries.get(uid, [])),
                "chats": self.chats.get(uid, {})}

    def delete_user(self, uid):
        api_keys = [k for k, r in self.keys.items() if r.user_id == uid]
        for k in api_keys:
            self.keys.pop(k, None)
        return {"deleted": True,
                "user": self.users.pop(uid, None) is not None,
                "ledger_entries": len(self.ledger_entries.pop(uid, [])),
                "chats": len(self.chats.pop(uid, {})),
                "api_keys": len(api_keys)}

    def mark_payment_processed(self, payment_id):
        if payment_id in self.processed_payments:
            return False
        self.processed_payments.add(payment_id)
        return True


class FirestoreStore(Store):
    """Durable store on Cloud Firestore (Native mode).

    Collections: api_keys/{key}, users/{uid}, usage/{key__YYYY-MM-DD},
    cache/{sha256(ck)}, jobs/{job_id}. Daily usage uses atomic Increment so
    concurrent instances count correctly. Per-minute rate limiting is kept
    in-process (good enough per instance); move to a shared counter later if
    you need strict global bursts.
    """

    def __init__(self, project: str):
        from google.cloud import firestore  # lazy import
        self._fs = firestore
        self._db = firestore.Client(project=project) if project else firestore.Client()
        self._rate: dict[str, list[float]] = {}

    # --- api keys (stored HASHED at rest; the raw key is never persisted) ---
    def _key_hash(self, key: str) -> str:
        pepper = get_settings().api_key_pepper or ""
        return hashlib.sha256((pepper + key).encode("utf-8")).hexdigest()

    def get_key(self, key):
        snap = self._db.collection("api_keys").document(self._key_hash(key)).get()
        if not snap.exists:
            return None
        d = snap.to_dict()
        return ApiKeyRecord(key=key, user_id=d.get("user_id", ""),
                            tier=d.get("tier", "free"), disabled=d.get("disabled", False))

    def create_key(self, key, user_id, tier):
        self._db.collection("api_keys").document(self._key_hash(key)).set(
            {"user_id": user_id, "tier": tier, "disabled": False, "prefix": key[:8]})
        return ApiKeyRecord(key=key, user_id=user_id, tier=tier)

    def set_tier(self, user_id, tier):
        self._db.collection("users").document(user_id).set({"tier": tier}, merge=True)
        for doc in self._db.collection("api_keys").where("user_id", "==", user_id).stream():
            doc.reference.set({"tier": tier}, merge=True)

    # --- users ---
    def get_user(self, uid):
        snap = self._db.collection("users").document(uid).get()
        return snap.to_dict() if snap.exists else None

    def upsert_user(self, uid, email, tier=None):
        ref = self._db.collection("users").document(uid)
        snap = ref.get()
        if snap.exists:
            data = snap.to_dict()
            if email and data.get("email") != email:
                ref.set({"email": email}, merge=True)
                data["email"] = email
            return data
        ref.set({"email": email or "", "tier": tier or "free",
                 "created_at": self._fs.SERVER_TIMESTAMP})
        return {"email": email or "", "tier": tier or "free"}

    # --- rate (per-instance) ---
    def hit_rate(self, key, per_minute):
        now = time.time()
        bucket = [t for t in self._rate.get(key, []) if now - t < 60]
        if len(bucket) >= per_minute:
            self._rate[key] = bucket
            return False
        bucket.append(now)
        self._rate[key] = bucket
        return True

    # --- usage (durable, atomic) ---
    def _usage_ref(self, key):
        return self._db.collection("usage").document(f"{key}__{date.today().isoformat()}")

    def usage_today(self, key):
        snap = self._usage_ref(key).get()
        d = snap.to_dict() if snap.exists else {}
        return {"calls": d.get("calls", 0), "readings": d.get("readings", 0),
                "tokens_in": d.get("tokens_in", 0), "tokens_out": d.get("tokens_out", 0)}

    def record(self, key, tokens_in, tokens_out, reading):
        Inc = self._fs.Increment
        today = date.today().isoformat()
        self._usage_ref(key).set({
            "calls": Inc(1),
            "readings": Inc(1 if reading else 0),
            "tokens_in": Inc(int(tokens_in)),
            "tokens_out": Inc(int(tokens_out)),
        }, merge=True)
        # platform-wide daily total for the global cost breaker
        self._db.collection("global_usage").document(today).set(
            {"tokens": Inc(int(tokens_in) + int(tokens_out))}, merge=True)

    def global_tokens_today(self):
        snap = self._db.collection("global_usage").document(date.today().isoformat()).get()
        return int((snap.to_dict() or {}).get("tokens", 0)) if snap.exists else 0

    def export_user(self, uid):
        uref = self._db.collection("users").document(uid)
        chats = []
        for c in uref.collection("chats").stream():
            msgs = [m.to_dict() for m in c.reference.collection("messages").stream()]
            chats.append({"id": c.id, **(c.to_dict() or {}), "messages": msgs})
        return {"user": self.get_user(uid), "ledger": self.credit_ledger(uid, limit=10000), "chats": chats}

    def delete_user(self, uid):
        uref = self._db.collection("users").document(uid)
        for entry in uref.collection("ledger").stream():
            entry.reference.delete()
        for c in uref.collection("chats").stream():
            for m in c.reference.collection("messages").stream():
                m.reference.delete()
            c.reference.delete()
        uref.delete()
        n = 0
        for doc in self._db.collection("api_keys").where("user_id", "==", uid).stream():
            doc.reference.delete()
            n += 1
        return {"deleted": True, "api_keys": n}

    # --- reading cache ---
    def _ck_id(self, ck):
        import hashlib
        return hashlib.sha256(ck.encode()).hexdigest()

    def cache_get(self, ck):
        snap = self._db.collection("cache").document(self._ck_id(ck)).get()
        return snap.to_dict().get("value") if snap.exists else None

    def cache_put(self, ck, value):
        self._db.collection("cache").document(self._ck_id(ck)).set({"value": value})

    # --- jobs ---
    def job_put(self, job_id, value):
        self._db.collection("jobs").document(job_id).set(value)

    def job_get(self, job_id):
        snap = self._db.collection("jobs").document(job_id).get()
        return snap.to_dict() if snap.exists else None

    # --- credit ledger (atomic via a Firestore transaction on users/{uid}) ---
    def _credit_apply(self, uid, tier, op, *, now=None, **kw) -> credits.Balance:
        now = now or _now()
        fs = self._fs
        user_ref = self._db.collection("users").document(uid)
        ledger_col = user_ref.collection("ledger")

        @fs.transactional
        def _run(transaction):
            snap = user_ref.get(transaction=transaction)
            doc = snap.to_dict() if snap.exists else {}
            bal, entries = _plan(_balance_from_doc(doc, now), tier, op, now, **kw)
            transaction.set(user_ref, _balance_to_doc(bal, now), merge=True)
            for e in entries:                       # append-only audit trail
                transaction.set(ledger_col.document(), e)
            return bal

        return _run(self._db.transaction())

    def credit_balance(self, uid, tier, now=None):
        return self._credit_apply(uid, tier, "read", now=now).as_public()

    def credit_debit(self, uid, tier, cost, reason="chat turn", ref=None, now=None):
        return self._credit_apply(uid, tier, "debit", now=now, cost=cost, reason=reason, ref=ref).as_public()

    def credit_topup(self, uid, tier, tokens, reason="top-up", ref=None, now=None):
        return self._credit_apply(uid, tier, "topup", now=now, tokens=tokens, reason=reason, ref=ref).as_public()

    def credit_grant(self, uid, tier, reason="monthly grant", now=None):
        return self._credit_apply(uid, tier, "grant", now=now, reason=reason).as_public()

    def credit_refund(self, uid, tier, tokens, reason="refund", ref=None, now=None):
        return self._credit_apply(uid, tier, "refund", now=now, tokens=tokens, reason=reason, ref=ref).as_public()

    def credit_ledger(self, uid, limit=20):
        q = (self._db.collection("users").document(uid).collection("ledger")
             .order_by("ts", direction=self._fs.Query.DESCENDING).limit(limit))
        return [d.to_dict() for d in q.stream()]

    # --- payment records + refund requests ---
    def record_payment(self, payment_id, data):
        self._db.collection("payments").document(payment_id).set({**data, "payment_id": payment_id}, merge=True)

    def get_payment(self, payment_id):
        snap = self._db.collection("payments").document(payment_id).get()
        return snap.to_dict() if snap.exists else None

    def set_payment_status(self, payment_id, status):
        self._db.collection("payments").document(payment_id).set({"status": status}, merge=True)

    def list_payments(self, uid):
        return [d.to_dict() for d in self._db.collection("payments").where("uid", "==", uid).stream()]

    def refund_request_create(self, req_id, data):
        self._db.collection("refund_requests").document(req_id).set({**data, "id": req_id})

    def refund_request_get(self, req_id):
        snap = self._db.collection("refund_requests").document(req_id).get()
        return snap.to_dict() if snap.exists else None

    def refund_request_set_status(self, req_id, status):
        self._db.collection("refund_requests").document(req_id).set({"status": status}, merge=True)

    def list_refund_requests(self, status=None):
        col = self._db.collection("refund_requests")
        q = col.where("status", "==", status) if status else col
        return [d.to_dict() for d in q.stream()]

    def chat_save_turn(self, uid, chat_id, chart_hash, user_text, assistant_text, tokens, msg_id, now=None):
        now = now or _now()
        chat_ref = (self._db.collection("users").document(uid)
                    .collection("chats").document(chat_id))
        chat_ref.set({"chart_hash": chart_hash, "created_at": now}, merge=True)
        msgs = chat_ref.collection("messages")
        exp = _chat_expire_at(now)   # set a Firestore TTL policy on `expireAt` to auto-purge
        u = {"role": "user", "text": user_text, "tokens": None, "ts": now}
        a = {"role": "assistant", "text": assistant_text, "tokens": int(tokens), "ts": now, "id": msg_id}
        if exp:
            u["expireAt"] = exp
            a["expireAt"] = exp
        msgs.document().set(u)
        msgs.document().set(a)
        return chat_id

    def mark_payment_processed(self, payment_id):
        # Atomic check-and-set so concurrent webhook retries can't double-credit.
        fs = self._fs
        ref = self._db.collection("processed_payments").document(payment_id)

        @fs.transactional
        def _run(transaction):
            if ref.get(transaction=transaction).exists:
                return False
            transaction.set(ref, {"ts": _now()})
            return True

        return _run(self._db.transaction())


_STORE: Store | None = None


def get_store() -> Store:
    global _STORE
    if _STORE is not None:
        return _STORE
    s = get_settings()
    if s.store_backend == "firestore":
        store = FirestoreStore(s.firestore_project or s.firebase_project or s.vertex_project)
        if s.app_env != "prod":   # dev convenience: seed dev keys (never in prod)
            for k, uid, t in (("free_dev_key", "u_free", "free"),
                              ("basic_dev_key", "u_basic", "basic"),
                              ("pro_dev_key", "u_pro", "pro"),
                              ("ent_dev_key", "u_ent", "enterprise")):
                if not store.get_key(k):
                    store.create_key(k, uid, t)
        _STORE = store
        return _STORE
    if s.store_backend == "postgres":
        raise NotImplementedError("PostgresStore: implement with SQLAlchemy/asyncpg (see ARCHITECTURE.md).")
    store = MemoryStore()
    # dev keys so the API is usable out of the box (DO NOT ship these) — never in prod
    if s.app_env != "prod":
        store.create_key("free_dev_key", "u_free", "free")
        store.create_key("basic_dev_key", "u_basic", "basic")
        store.create_key("pro_dev_key", "u_pro", "pro")
        store.create_key("ent_dev_key", "u_ent", "enterprise")
    _STORE = store
    return _STORE


# --------------------------------------------------------------------------- #
# auth + quota
# --------------------------------------------------------------------------- #
@dataclass
class Principal:
    user_id: str
    key: str
    tier: Tier


async def require_key(x_api_key: str | None = Header(default=None)) -> Principal:
    if not x_api_key:
        raise HTTPException(401, "Missing X-API-Key header")
    rec = get_store().get_key(x_api_key)
    if not rec or rec.disabled:
        raise HTTPException(401, "Invalid or disabled API key")
    tier = TIERS.get(rec.tier) or TIERS["free"]
    return Principal(user_id=rec.user_id, key=rec.key, tier=tier)


def enforce_global_breaker() -> None:
    """Hard stop on total platform LLM spend for the day (financial-DoS backstop)."""
    s = get_settings()
    cap = s.daily_global_token_breaker
    if cap and get_store().global_tokens_today() >= cap:
        raise HTTPException(503, "Service temporarily paused: daily usage cap reached. Try again tomorrow.")


def enforce_quota(p: Principal) -> None:
    store = get_store()
    if not store.hit_rate(p.key, p.tier.per_minute):
        raise HTTPException(429, f"Rate limit exceeded ({p.tier.per_minute}/min on {p.tier.label})")
    if store.usage_today(p.key)["calls"] >= p.tier.daily_limit:
        raise HTTPException(429, f"Daily limit reached ({p.tier.daily_limit}/day on {p.tier.label}). Upgrade for more.")


# Weak/placeholder secrets are rejected in EVERY environment (not just prod), so a
# default credential can never authorize admin/internal access by accident.
_WEAK_ADMIN_KEYS = {"", "admin_dev_key", "change-me"}
_WEAK_INTERNAL_TOKENS = {"", "internal_dev_token"}


def _ct_eq(a: str | None, b: str) -> bool:
    """Constant-time string compare (no early-exit timing oracle)."""
    return bool(a) and hmac.compare_digest(a, b)


async def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    s = get_settings()
    # Fail closed: a default/placeholder key disables admin entirely.
    if s.admin_api_key in _WEAK_ADMIN_KEYS:
        raise HTTPException(503, "Admin disabled: set a strong ADMIN_API_KEY (Secret Manager)")
    if not _ct_eq(x_admin_key, s.admin_api_key):
        raise HTTPException(403, "Admin key required")
