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

from fastapi import Header, HTTPException, Request

from .config import get_settings
from .billing import Principal, TIERS, get_store, require_key, require_admin as _key_admin

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
    check = get_settings().verify_token_revocation
    try:
        decoded = fb_auth.verify_id_token(token, check_revoked=check)
    except (fb_auth.RevokedIdTokenError, fb_auth.UserDisabledError) as exc:
        log.info("session revoked/disabled: %s", exc)
        raise HTTPException(401, "Your session was revoked. Please sign in again.")
    except fb_auth.InvalidIdTokenError as exc:          # bad signature / expired / malformed
        log.info("invalid sign-in token: %s", exc)
        raise HTTPException(401, "Invalid or expired sign-in token")
    except Exception as exc:  # noqa: BLE001
        # The revocation check makes an Admin-API call (get_user) that needs Firebase
        # Auth permission on the runtime SA. If THAT call fails (missing IAM role,
        # transient outage) we must NOT lock every signed-in user out — the JWT
        # signature/expiry was already validated. Fall back to a non-revoked verify
        # and loudly log the misconfiguration so it gets fixed.
        if check:
            log.error("revocation check failed (server-side, not the user's token): %s "
                      "- falling back to signature/expiry verify. Grant the runtime SA "
                      "roles/firebaseauth.viewer to restore revocation checking.", exc)
            try:
                decoded = fb_auth.verify_id_token(token, check_revoked=False)
            except Exception as exc2:  # noqa: BLE001
                log.info("token verification failed: %s", exc2)
                raise HTTPException(401, "Invalid or expired sign-in token")
        else:
            log.info("token verification failed: %s", exc)
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


def _client_ip(request: Request) -> str:
    """Real caller IP, SPOOF-RESISTANT.

    A client can prepend a fake X-Forwarded-For; Cloud Run / the load balancer then
    APPENDS the true source IP on the right. So the trustworthy client IP is the
    `trusted_proxy_depth`-th hop from the END (default 1 = the value the platform
    appended), not the left-most (which the client controls). Falls back to the
    socket peer when no XFF is present."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            depth = max(1, get_settings().trusted_proxy_depth)
            idx = len(parts) - depth
            return parts[idx] if idx >= 0 else parts[0]
    return request.client.host if request.client else "?"


def _enforce_and_track(p: Principal, request: Request) -> None:
    """Block banned accounts (403) and record IP/activity for every auth'd request."""
    store = get_store()
    ban = store.is_banned(p.user_id)
    if ban:
        raise HTTPException(403, f"Account suspended: {ban.get('reason') or 'policy violation'}")
    try:
        store.record_activity(p.user_id, _client_ip(request))
    except Exception:  # noqa: BLE001, never fail a request on activity logging
        log.warning("activity logging failed uid=%s", p.user_id)


async def require_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> Principal:
    """Accept a Firebase bearer token (app users) or an X-API-Key (programmatic).
    Then enforce bans and capture the caller IP."""
    if authorization and authorization.lower().startswith("bearer "):
        decoded = _verify_bearer(authorization.split(" ", 1)[1].strip())
        p = _principal_from_uid(decoded["uid"], decoded.get("email"))
    elif x_api_key:
        p = await require_key(x_api_key)
    else:
        raise HTTPException(401, "Provide a Firebase bearer token (Authorization: Bearer ...) or X-API-Key")
    _enforce_and_track(p, request)
    return p


async def require_admin(
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None),
) -> str:
    """Admin access via EITHER a Firebase ID token with an `admin` custom claim
    (so the web dashboard needs no server secret in the browser) OR an X-Admin-Key
    (programmatic). The X-Admin-Key path is fail-closed on weak/unset secrets.
    Returns an identity string for audit logging (email/uid, or 'api-key')."""
    if authorization and authorization.lower().startswith("bearer "):
        decoded = _verify_bearer(authorization.split(" ", 1)[1].strip())
        if decoded.get("admin") is True:
            return decoded.get("email") or decoded.get("uid") or "admin"
        raise HTTPException(403, "Admin privilege required")
    await _key_admin(x_admin_key)
    return "api-key"
