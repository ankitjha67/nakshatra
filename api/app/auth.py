"""Firebase Authentication (Google sign-in) -> Principal.

The frontend signs the user in with Firebase (Google) and sends the resulting
ID token as `Authorization: Bearer <token>`. We verify it with firebase-admin,
map the uid to a user record (auto-created on first sign-in at the default
tier), and reuse the same Principal / quota machinery as API keys.

`require_principal` accepts EITHER a Firebase bearer token (the app) OR an
X-API-Key (programmatic / B2B), so both audiences hit one set of endpoints.
"""
from __future__ import annotations

import logging

from fastapi import Header, HTTPException

from .config import get_settings
from .billing import Principal, TIERS, get_store, require_key

log = logging.getLogger("auth")

_FB_READY = False


def _ensure_firebase() -> None:
    global _FB_READY
    if _FB_READY:
        return
    import firebase_admin
    from firebase_admin import credentials
    s = get_settings()
    project = s.firebase_project or s.firestore_project or s.vertex_project
    if not firebase_admin._apps:  # initialise once, using ADC (Cloud Run SA / local gcloud)
        opts = {"projectId": project} if project else None
        firebase_admin.initialize_app(credentials.ApplicationDefault(), opts)
    _FB_READY = True


def _verify_bearer(token: str) -> dict:
    _ensure_firebase()
    from firebase_admin import auth as fb_auth
    try:
        decoded = fb_auth.verify_id_token(token, check_revoked=get_settings().verify_token_revocation)
    except Exception as exc:  # noqa: BLE001 — surface as 401, not 500
        log.warning("Firebase token verification failed: %s", exc)
        raise HTTPException(401, "Invalid or expired sign-in token")
    if get_settings().require_email_verified and not decoded.get("email_verified", False):
        raise HTTPException(403, "Please verify your email address to continue.")
    return decoded


def _principal_from_uid(uid: str, email: str | None) -> Principal:
    store = get_store()
    s = get_settings()
    user = store.get_user(uid) or store.upsert_user(uid, email, tier=s.default_user_tier)
    tier_key = (user or {}).get("tier") or s.default_user_tier
    tier = TIERS.get(tier_key) or TIERS["free"]
    return Principal(user_id=uid, key=uid, tier=tier)


def delete_firebase_user(uid: str) -> bool:
    """Best-effort deletion of the Firebase Auth identity (GDPR erasure). No-op for
    non-Firebase principals (e.g. B2B API keys) or when Admin SDK is unavailable."""
    try:
        _ensure_firebase()
        from firebase_admin import auth as fb_auth
        fb_auth.delete_user(uid)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("firebase identity delete skipped uid=%s err=%s", uid, type(exc).__name__)
        return False


async def require_user(authorization: str | None = Header(default=None)) -> Principal:
    """Firebase-only dependency (used where an app login is mandatory)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    decoded = _verify_bearer(authorization.split(" ", 1)[1].strip())
    return _principal_from_uid(decoded["uid"], decoded.get("email"))


async def require_principal(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> Principal:
    """Accept a Firebase bearer token (app users) or an X-API-Key (programmatic)."""
    if authorization and authorization.lower().startswith("bearer "):
        decoded = _verify_bearer(authorization.split(" ", 1)[1].strip())
        return _principal_from_uid(decoded["uid"], decoded.get("email"))
    if x_api_key:
        return await require_key(x_api_key)
    raise HTTPException(401, "Provide a Firebase bearer token (Authorization: Bearer ...) or X-API-Key")
