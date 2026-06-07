"""Control plane: tiers, store, auth, quota.

Everything an end user is *entitled* to is defined in TIERS. The store keeps API
keys, user records (Firebase-authenticated), usage counters, the reading cache,
and async jobs. The memory backend boots with dev keys so you can try the API
immediately; the Firestore backend persists all of it for production.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from fastapi import Header, HTTPException

from .config import get_settings


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

    @property
    def reading_allowed(self) -> bool:
        return self.llm and bool(self.sections)


ALL_SECTIONS = frozenset({
    "essence", "mind", "relationships", "career", "wealth", "family", "health",
    "timing", "fortune", "spirit", "strengths", "kp", "panchang", "alerts",
    "numbers", "remedies",
})

TIERS: dict[str, Tier] = {
    "free":  Tier("free",  "Free",        0,    frozenset(),                       False, 5,    3),
    "basic": Tier("basic", "Basic",       299,  frozenset({"essence", "mind", "relationships", "career", "timing"}), True, 50, 10),
    "pro":   Tier("pro",   "Pro",         999,  ALL_SECTIONS,                      True,  500,  30, allow_async=True),
    "enterprise": Tier("enterprise", "API / Business", 4999, ALL_SECTIONS,         True,  10000, 120, allow_async=True, api_access=True),
}


def tier_catalog() -> list[dict]:
    return [{
        "key": t.key, "label": t.label, "price_inr_month": t.price_inr_month,
        "reading": t.reading_allowed, "sections": sorted(t.sections),
        "daily_limit": t.daily_limit, "per_minute": t.per_minute,
        "async": t.allow_async, "api_access": t.api_access,
    } for t in TIERS.values()]


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


@dataclass
class MemoryStore(Store):
    keys: dict[str, ApiKeyRecord] = field(default_factory=dict)
    users: dict[str, dict] = field(default_factory=dict)
    usage: dict[tuple[str, str], dict] = field(default_factory=dict)
    rate: dict[str, list[float]] = field(default_factory=dict)
    reading_cache: dict[str, dict] = field(default_factory=dict)
    jobs: dict[str, dict] = field(default_factory=dict)

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
        k = (key, date.today().isoformat())
        u = self.usage.get(k, {"calls": 0, "readings": 0, "tokens_in": 0, "tokens_out": 0})
        u["calls"] += 1
        u["readings"] += 1 if reading else 0
        u["tokens_in"] += tokens_in
        u["tokens_out"] += tokens_out
        self.usage[k] = u

    def cache_get(self, ck):
        return self.reading_cache.get(ck)

    def cache_put(self, ck, value):
        self.reading_cache[ck] = value

    def job_put(self, job_id, value):
        self.jobs[job_id] = value

    def job_get(self, job_id):
        return self.jobs.get(job_id)


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

    # --- api keys ---
    def get_key(self, key):
        snap = self._db.collection("api_keys").document(key).get()
        if not snap.exists:
            return None
        d = snap.to_dict()
        return ApiKeyRecord(key=key, user_id=d.get("user_id", ""),
                            tier=d.get("tier", "free"), disabled=d.get("disabled", False))

    def create_key(self, key, user_id, tier):
        self._db.collection("api_keys").document(key).set(
            {"user_id": user_id, "tier": tier, "disabled": False})
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
        self._usage_ref(key).set({
            "calls": Inc(1),
            "readings": Inc(1 if reading else 0),
            "tokens_in": Inc(int(tokens_in)),
            "tokens_out": Inc(int(tokens_out)),
        }, merge=True)

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
    # dev keys so the API is usable out of the box (DO NOT ship these)
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


def enforce_quota(p: Principal) -> None:
    store = get_store()
    if not store.hit_rate(p.key, p.tier.per_minute):
        raise HTTPException(429, f"Rate limit exceeded ({p.tier.per_minute}/min on {p.tier.label})")
    if store.usage_today(p.key)["calls"] >= p.tier.daily_limit:
        raise HTTPException(429, f"Daily limit reached ({p.tier.daily_limit}/day on {p.tier.label}). Upgrade for more.")


async def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    if x_admin_key != get_settings().admin_api_key:
        raise HTTPException(403, "Admin key required")
