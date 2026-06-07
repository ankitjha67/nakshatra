"""Engine boundary.

This is the ONE place your calculation code plugs in. Set in the environment:

    ENGINE_MODULE=maha_jyotish.api        # importable module
    ENGINE_CALLABLE=compute_chart         # def compute_chart(birth: dict) -> dict
    ENGINE_VERSION=maha-jyotish-7.0

Your callable receives a plain dict (the BirthDetails fields) and must return a
JSON-serialisable dict — whatever your engine already emits. The rules layer is
written defensively, so it adapts to common shapes; see app/rules.py for the
fields it looks for. If the import fails for any reason, the bundled mock engine
runs instead so the service always boots (handy in CI and for the frontend).
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Callable

from .config import get_settings
from .models import BirthDetails
from . import ENGINE_VERSION_FALLBACK
from .mock_engine import compute_mock_chart

log = logging.getLogger("engine")

_ENGINE: Callable[[dict], dict] | None = None
_ENGINE_VERSION: str = ENGINE_VERSION_FALLBACK
_LOADED = False


def _load() -> None:
    global _ENGINE, _ENGINE_VERSION, _LOADED
    _LOADED = True
    s = get_settings()
    if not s.engine_module:
        log.warning("No ENGINE_MODULE set — using bundled mock engine.")
        _ENGINE = compute_mock_chart
        _ENGINE_VERSION = s.engine_version or ENGINE_VERSION_FALLBACK
        return
    try:
        mod = importlib.import_module(s.engine_module)
        fn = getattr(mod, s.engine_callable)
        _ENGINE = fn
        _ENGINE_VERSION = s.engine_version or getattr(mod, "__version__", "engine-unknown")
        log.info("Loaded engine %s.%s (v%s)", s.engine_module, s.engine_callable, _ENGINE_VERSION)
    except Exception as exc:  # noqa: BLE001 — never let a bad import take the service down
        log.error("Engine import failed (%s); falling back to mock.", exc)
        _ENGINE = compute_mock_chart
        _ENGINE_VERSION = ENGINE_VERSION_FALLBACK


def engine_version() -> str:
    if not _LOADED:
        _load()
    return _ENGINE_VERSION


def compute_chart(birth: BirthDetails) -> dict[str, Any]:
    """Run the active engine and return its JSON chart."""
    if not _LOADED:
        _load()
    assert _ENGINE is not None
    out = _ENGINE(birth.model_dump())
    if not isinstance(out, dict):
        raise TypeError("Engine must return a JSON-serialisable dict")
    return out
