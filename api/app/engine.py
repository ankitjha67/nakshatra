"""Engine boundary.

This is the ONE place your calculation code plugs in. Set in the environment:

    ENGINE_MODULE=maha_jyotish.api        # importable module
    ENGINE_CALLABLE=compute_chart         # def compute_chart(birth: dict) -> dict
    ENGINE_VERSION=maha-jyotish-7.0

Your callable receives a plain dict (the BirthDetails fields) and must return a
JSON-serialisable dict, whatever your engine already emits. The rules layer is
written defensively, so it adapts to common shapes; see app/rules.py for the
fields it looks for. If the import fails for any reason, the bundled mock engine
runs instead so the service always boots (handy in CI and for the frontend).
"""
from __future__ import annotations

import importlib
import logging
import threading
from typing import Any, Callable

from .config import get_settings
from .models import BirthDetails
from . import ENGINE_VERSION_FALLBACK
from .mock_engine import compute_mock_chart, rectify_mock

log = logging.getLogger("engine")

_ENGINE: Callable[[dict], dict] | None = None
_ENGINE_VERSION: str = ENGINE_VERSION_FALLBACK
_LOADED = False
_LOCK = threading.Lock()           # guards the lazy import (Cloud Run serves requests concurrently)

_RECTIFY: Callable[[dict], dict] | None = None
_RECTIFY_LOADED = False
_RECTIFY_LOCK = threading.Lock()


def _load_impl() -> None:
    """Bind _ENGINE/_ENGINE_VERSION. Always leaves _ENGINE non-None (mock fallback).
    Does NOT touch _LOADED, the caller sets that only after this completes, so a
    concurrent request never sees _LOADED=True with _ENGINE still None."""
    global _ENGINE, _ENGINE_VERSION
    s = get_settings()
    if not s.engine_module:
        log.warning("No ENGINE_MODULE set, using bundled mock engine.")
        _ENGINE = compute_mock_chart
        _ENGINE_VERSION = s.engine_version or ENGINE_VERSION_FALLBACK
        return
    try:
        mod = importlib.import_module(s.engine_module)
        fn = getattr(mod, s.engine_callable)
        _ENGINE = fn
        _ENGINE_VERSION = s.engine_version or getattr(mod, "__version__", "engine-unknown")
        log.info("Loaded engine %s.%s (v%s)", s.engine_module, s.engine_callable, _ENGINE_VERSION)
    except Exception as exc:  # noqa: BLE001, never let a bad import take the service down
        log.error("Engine import failed (%s); falling back to mock.", exc)
        _ENGINE = compute_mock_chart
        _ENGINE_VERSION = ENGINE_VERSION_FALLBACK


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOCK:                     # double-checked locking: only one thread imports
        if _LOADED:
            return
        _load_impl()
        _LOADED = True             # set last, so concurrent callers wait then see a ready engine


def engine_version() -> str:
    _ensure_loaded()
    return _ENGINE_VERSION


def compute_chart(birth: BirthDetails) -> dict[str, Any]:
    """Run the active engine and return its JSON chart."""
    _ensure_loaded()
    assert _ENGINE is not None
    out = _ENGINE(birth.model_dump())
    if not isinstance(out, dict):
        raise TypeError("Engine must return a JSON-serialisable dict")
    return out


def _load_rectify_impl() -> None:
    """Bind the engine's rectify_birth_time callable; fall back to the mock so the
    BTR endpoint always responds (the proprietary engine isn't present in dev/CI).
    Always leaves _RECTIFY non-None; does not touch _RECTIFY_LOADED."""
    global _RECTIFY
    s = get_settings()
    if not s.engine_module:
        _RECTIFY = rectify_mock
        return
    try:
        mod = importlib.import_module(s.engine_module)
        _RECTIFY = getattr(mod, s.engine_rectify_callable)
        log.info("Loaded rectifier %s.%s", s.engine_module, s.engine_rectify_callable)
    except Exception as exc:  # noqa: BLE001
        log.error("Rectifier import failed (%s); falling back to mock.", exc)
        _RECTIFY = rectify_mock


def rectify_birth_time(payload: dict) -> dict[str, Any]:
    """Run the active rectifier on a BTR payload; returns the engine's
    birth_time_rectification block (candidates + confidence across methods)."""
    global _RECTIFY_LOADED
    if not _RECTIFY_LOADED:
        with _RECTIFY_LOCK:
            if not _RECTIFY_LOADED:
                _load_rectify_impl()
                _RECTIFY_LOADED = True
    assert _RECTIFY is not None
    out = _RECTIFY(payload)
    if not isinstance(out, dict):
        raise TypeError("Rectifier must return a JSON-serialisable dict")
    return out
