"""Age gate (DPDP s9 / GDPR Art 8): we only onboard users who attest they are an
adult. /v1/consent requires `is_adult`; without it processing must be refused, and
the attestation is recorded so we have an auditable "we do not knowingly onboard
children" record. Also covers the store-level persistence of the flag.
"""
from fastapi.testclient import TestClient

from app import billing
from app.auth import require_principal
from app.billing import MemoryStore, Principal, TIERS
from app.main import app


def _client():
    store = MemoryStore()
    billing._STORE = store                                   # endpoints read this global
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="u1", key="u1", tier=TIERS["free"])
    return TestClient(app), store


def teardown_function():
    app.dependency_overrides.clear()
    billing._STORE = None


def test_consent_without_adult_attestation_is_refused():
    client, store = _client()
    r = client.post("/v1/consent", json={"version": "2026-06-25"})       # is_adult defaults False
    assert r.status_code == 403
    assert "18" in r.json()["detail"]
    assert not (store.get_user("u1") or {}).get("adult_confirmed")
    assert not (store.get_user("u1") or {}).get("consent_version")        # nothing recorded


def test_consent_with_adult_attestation_is_recorded():
    client, store = _client()
    r = client.post("/v1/consent", json={"version": "2026-06-25", "is_adult": True})
    assert r.status_code == 200
    u = store.get_user("u1")
    assert u["consent_version"] == "2026-06-25"
    assert u["adult_confirmed"] is True
    assert u.get("adult_confirmed_at")


def test_me_exposes_adult_confirmed_flag():
    client, store = _client()
    assert client.get("/v1/me").json()["adult_confirmed"] is False
    client.post("/v1/consent", json={"version": "2026-06-25", "is_adult": True})
    assert client.get("/v1/me").json()["adult_confirmed"] is True


def test_store_set_consent_default_does_not_mark_adult():
    s = MemoryStore()
    s.set_consent("u9", "v1")                                 # no is_adult
    assert s.get_user("u9")["consent_version"] == "v1"
    assert not s.get_user("u9").get("adult_confirmed")
