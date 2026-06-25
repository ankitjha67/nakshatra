"""Hardening from the SSTI/ReDoS/DoS/secret/replay audit:
- request body-size limit (anti-DoS, guards the pre-auth webhook),
- data export now includes payments + the sub-processor (recipient) list.
"""
from fastapi.testclient import TestClient

from app import billing
from app.auth import require_principal
from app.billing import MemoryStore, Principal, TIERS
from app.config import get_settings
from app.main import app


def _client():
    store = MemoryStore()
    billing._STORE = store
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="u1", key="u1", tier=TIERS["pro"])
    return TestClient(app), store


def teardown_function():
    app.dependency_overrides.clear()
    billing._STORE = None
    get_settings().max_request_bytes = 1_000_000      # restore default


def test_oversized_body_is_rejected_413():
    client, _ = _client()
    get_settings().max_request_bytes = 200            # tiny cap for the test
    big = {"version": "x" * 500}
    r = client.post("/v1/consent", json=big)
    assert r.status_code == 413


def test_normal_body_passes_size_check():
    client, _ = _client()
    r = client.post("/v1/consent", json={"version": "2026-06-25", "is_adult": True})
    assert r.status_code == 200                        # well under the 1MB default


def test_nominee_rejects_invalid_email():
    client, _ = _client()
    bad = client.post("/v1/nominee", json={"name": "X", "email": "not-an-email"})
    assert bad.status_code == 422
    ok = client.post("/v1/nominee", json={"name": "X", "email": "a@b.com"})
    assert ok.status_code == 200


def test_prashna_input_bounds():
    from pydantic import ValidationError
    import pytest
    from app.main import PrashnaRequest
    PrashnaRequest(question="hi?", lat=0, lon=0)                       # ok
    with pytest.raises(ValidationError):
        PrashnaRequest(question="hi?", lat=0, lon=0, tz="+" * 100)     # tz bounded
    with pytest.raises(ValidationError):
        PrashnaRequest(question="hi?", lat=0, lon=0, category="x" * 100)


def test_rate_limiter_denies_at_limit():
    # Contract honoured by both the in-process (dev) and the shared Firestore (prod)
    # limiter: allow up to per_minute, then deny within the same window.
    s = MemoryStore()
    allowed = sum(1 for _ in range(5) if s.hit_rate("k", 3))
    assert allowed == 3                                # 4th and 5th denied
    assert s.hit_rate("k", 0) is True                  # 0 = unlimited / disabled


def test_export_includes_payments_and_recipients():
    client, store = _client()
    store.credit_balance("u1", TIERS["pro"])           # creates user + opening grant
    store.record_payment("pay_1", {"uid": "u1", "kind": "subscription", "amount_inr": 999,
                                   "status": "captured"})
    data = client.get("/v1/me/export").json()
    assert any(p.get("payment_id") == "pay_1" or p.get("uid") == "u1" for p in data["payments"])
    names = [r["name"] for r in data["recipients"]]
    assert "Razorpay" in names and any("Vertex" in n for n in names)
    assert data["exported_at"]
