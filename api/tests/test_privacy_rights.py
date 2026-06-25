"""Phase 2 privacy rights: consent withdrawal (DPDP s6), grievance intake (s13),
and nomination (s14)."""
from fastapi.testclient import TestClient

from app import billing
from app.auth import require_principal, require_admin
from app.billing import MemoryStore, Principal, TIERS
from app.main import app


def _client():
    store = MemoryStore()
    billing._STORE = store
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="u1", key="u1", tier=TIERS["free"])
    return TestClient(app), store


def teardown_function():
    app.dependency_overrides.clear()
    billing._STORE = None


def test_withdraw_consent_clears_consent_and_forces_reconsent():
    client, store = _client()
    client.post("/v1/consent", json={"version": "v1", "is_adult": True})
    assert store.get_user("u1")["adult_confirmed"] is True
    r = client.post("/v1/consent/withdraw")
    assert r.status_code == 200 and r.json()["ok"] is True
    u = store.get_user("u1")
    assert u.get("consent_withdrawn_at")
    assert "consent_version" not in u            # must re-consent before further processing
    assert "adult_confirmed" not in u


def test_grievance_is_recorded_and_listed():
    client, store = _client()
    r = client.post("/v1/grievance", json={"message": "Please delete my chat history."})
    assert r.status_code == 200
    rows = store.list_grievances()
    assert len(rows) == 1 and rows[0]["uid"] == "u1" and rows[0]["status"] == "open"


def test_nominee_set_get_clear():
    client, store = _client()
    assert client.get("/v1/nominee").json()["nominee"] is None
    client.post("/v1/nominee", json={"name": "A. Nominee", "email": "n@x.com", "relationship": "spouse"})
    assert client.get("/v1/nominee").json()["nominee"]["name"] == "A. Nominee"
    client.delete("/v1/nominee")
    assert client.get("/v1/nominee").json()["nominee"] is None


def test_me_exposes_nominee_and_officer():
    client, store = _client()
    body = client.get("/v1/me").json()
    assert "nominee" in body and "grievance_officer" in body


def test_admin_breach_register_records_and_lists():
    client, store = _client()
    app.dependency_overrides[require_admin] = lambda: "test-admin"
    r = client.post("/admin/breach", json={"description": "Test exposure of N user docs",
                                           "severity": "high", "affected_count": 3})
    assert r.status_code == 200 and r.json()["breach"]["by"] == "test-admin"
    rows = client.get("/admin/breaches").json()
    assert rows["count"] == 1 and rows["breaches"][0]["severity"] == "high"
