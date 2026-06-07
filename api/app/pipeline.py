"""Orchestration: ties the four stages together with caching.

Charts and readings are deterministic, so both are cached. The reading cache key
includes every stage version + the model + the unlocked sections, so a Basic
reading and a Pro reading of the same birth are cached separately, and bumping
any stage safely busts the cache.
"""
from __future__ import annotations

from .engine import compute_chart, engine_version
from .rules import derive_findings
from .llm import render_reading, get_provider, DISCLAIMERS
from .models import BirthDetails, ChartResponse, ReadingResponse, Meta
from .billing import Tier, get_store
from . import RULES_VERSION, RENDERER_VERSION


def get_chart(birth: BirthDetails, use_cache: bool = True) -> ChartResponse:
    store = get_store()
    ev = engine_version()
    ck = f"chart:{birth.chart_hash()}:{ev}"
    if use_cache:
        cached = store.cache_get(ck)
        if cached:
            meta = Meta(**cached["meta"]); meta.cache_hit = True
            return ChartResponse(chart=cached["chart"], meta=meta)
    chart = compute_chart(birth)
    meta = Meta(engine_version=ev, chart_hash=birth.chart_hash(), cache_hit=False)
    resp = ChartResponse(chart=chart, meta=meta)
    store.cache_put(ck, resp.model_dump())
    return resp


def get_reading(birth: BirthDetails, tier: Tier) -> ReadingResponse:
    store = get_store()
    ev = engine_version()
    model = get_provider().model or get_provider().name
    secs = sorted(tier.sections)
    ck = f"read:{birth.chart_hash()}:{ev}:{RULES_VERSION}:{RENDERER_VERSION}:{model}:{'|'.join(secs)}"

    if tier.cache:
        cached = store.cache_get(ck)
        if cached:
            meta = Meta(**cached["meta"]); meta.cache_hit = True; meta.tier = tier.key
            meta.tokens_in = 0; meta.tokens_out = 0
            return ReadingResponse(summary=cached["summary"],
                                   sections=[s for s in cached["sections"]],
                                   findings=cached["findings"],
                                   disclaimers=cached["disclaimers"], meta=meta)

    chart = compute_chart(birth)
    findings = derive_findings(chart)
    summary, sections, model_name, ti, to = render_reading(chart, findings, set(tier.sections))
    meta = Meta(engine_version=ev, rules_version=RULES_VERSION, renderer_version=RENDERER_VERSION,
                model=model_name, tier=tier.key, cache_hit=False,
                tokens_in=ti, tokens_out=to, chart_hash=birth.chart_hash())
    resp = ReadingResponse(summary=summary, sections=sections, findings=findings,
                           disclaimers=DISCLAIMERS, meta=meta)
    if tier.cache:
        store.cache_put(ck, resp.model_dump())
    return resp
