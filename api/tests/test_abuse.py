"""Abuse controls: bans (permanent/temporary/expiry), activity/IP capture."""
from datetime import datetime, timedelta, timezone

from app.billing import MemoryStore

UTC = timezone.utc
NOW = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)


def test_permanent_ban_active():
    s = MemoryStore()
    s.set_ban("u1", "permanent", "fraud", None, "admin")
    assert s.is_banned("u1", NOW)["kind"] == "permanent"


def test_temporary_ban_active_then_expires():
    s = MemoryStore()
    s.set_ban("u1", "temporary", "spam", NOW + timedelta(days=7), "admin")
    assert s.is_banned("u1", NOW) is not None                     # within window
    assert s.is_banned("u1", NOW + timedelta(days=8)) is None      # expired -> cleared


def test_unban_clears():
    s = MemoryStore()
    s.set_ban("u1", "permanent", "x", None, "admin")
    s.clear_ban("u1")
    assert s.is_banned("u1", NOW) is None


def test_not_banned_by_default():
    assert MemoryStore().is_banned("nobody", NOW) is None


def test_record_activity_captures_ip():
    s = MemoryStore()
    s.record_activity("u1", "203.0.113.7", NOW)
    s.record_activity("u1", "203.0.113.7", NOW)
    s.record_activity("u1", "198.51.100.2", NOW)
    a = s.get_activity("u1")
    assert a["last_ip"] == "198.51.100.2" and a["requests"] == 3
    assert set(a["ips"]) == {"203.0.113.7", "198.51.100.2"}        # de-duped history
