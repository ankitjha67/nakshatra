"""One-native-per-account lock: person_key semantics + store lock lifecycle."""
from app.billing import MemoryStore
from app.models import BirthDetails


def _b(date="1992-12-11", time="18:21", lat=23.54, lon=87.30):
    return BirthDetails(date=date, time=time, tz="+05:30", lat=lat, lon=lon)


def test_person_key_ignores_time_but_not_person():
    base = _b()
    assert _b(time="06:00").person_key() == base.person_key()      # time-only change = same person (BTR/typo)
    assert _b(date="1990-01-01").person_key() != base.person_key()  # different DOB = different person
    assert _b(lat=28.61, lon=77.20).person_key() != base.person_key()  # different place = different person


def test_birth_lock_store_lifecycle():
    s = MemoryStore()
    s.upsert_user("u1", "a@b.com")
    assert s.get_birth_lock("u1") is None
    s.set_birth_lock("u1", {"person_key": _b().person_key(), "date": "1992-12-11"})
    assert s.get_birth_lock("u1")["person_key"] == _b().person_key()
    s.clear_birth_lock("u1")
    assert s.get_birth_lock("u1") is None


def test_set_subscription():
    s = MemoryStore()
    s.upsert_user("u1", "a@b.com")
    s.set_subscription("u1", "sub_123")
    assert s.get_user("u1")["subscription_id"] == "sub_123"


def test_change_request_lifecycle():
    s = MemoryStore()
    s.set_birth_lock("u1", {"person_key": "k", "date": "1992-12-11"})
    s.create_change_request({"id": "r1", "uid": "u1", "reason": "typo in DOB", "status": "pending"})
    assert s.user_open_change_request("u1")["id"] == "r1"
    assert len(s.list_change_requests(status="pending")) == 1
    # a second open request is what the endpoint blocks (one at a time)
    s.create_change_request({"id": "r2", "uid": "u2", "reason": "x", "status": "pending"})
    assert len(s.list_change_requests(status="pending")) == 2
    # approve r1 -> resolved + lock cleared
    s.update_change_request("r1", {"status": "approved"})
    s.clear_birth_lock("u1")
    assert s.user_open_change_request("u1") is None
    assert s.get_birth_lock("u1") is None
    assert len(s.list_change_requests(status="pending")) == 1
