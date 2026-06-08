"""Orchestration: ties the four stages together with caching.

Charts and readings are deterministic, so both are cached. The reading cache key
includes every stage version + the model + the unlocked sections, so a Basic
reading and a Pro reading of the same birth are cached separately, and bumping
any stage safely busts the cache.
"""
from __future__ import annotations

from datetime import date

from .engine import compute_chart, engine_version
from .rules import derive_findings
from .varshphal import compute_varshphal
from .llm import render_reading, get_provider, DISCLAIMERS
from .models import BirthDetails, ChartResponse, ReadingResponse, Meta
from .billing import Tier, get_store, report_sections
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
    # Effective sections = what this report asks for ∩ what the tier unlocks. So a
    # Basic user requesting maha_kundali still only gets their unlocked sections.
    report_type = birth.report_type
    # Yearly (Varshphal) is scoped to a calendar year; default to the current year.
    year = (birth.year or date.today().year) if report_type == "yearly" else None
    eff_sections = report_sections(report_type) & set(tier.sections)
    secs = sorted(eff_sections)
    ck = (f"read:{birth.chart_hash()}:{ev}:{RULES_VERSION}:{RENDERER_VERSION}:"
          f"{model}:{report_type}" + (f":{year}" if year is not None else "") + f":{'|'.join(secs)}")

    if tier.cache:
        cached = store.cache_get(ck)
        if cached:
            meta = Meta(**cached["meta"]); meta.cache_hit = True; meta.tier = tier.key
            meta.tokens_in = 0; meta.tokens_out = 0
            return ReadingResponse(summary=cached["summary"],
                                   sections=[s for s in cached["sections"]],
                                   findings=cached["findings"],
                                   disclaimers=cached["disclaimers"], meta=meta,
                                   varshphal=cached.get("varshphal"))

    chart = compute_chart(birth)
    findings = derive_findings(chart, year=year)
    summary, sections, model_name, ti, to = render_reading(chart, findings, eff_sections)
    meta = Meta(engine_version=ev, rules_version=RULES_VERSION, renderer_version=RENDERER_VERSION,
                model=model_name, tier=tier.key, report_type=report_type, year=year, cache_hit=False,
                tokens_in=ti, tokens_out=to, chart_hash=birth.chart_hash())
    # Tajik Varshphal block (deterministic from natal chart + year) for yearly reports
    varshphal = compute_varshphal(chart, birth, year) if (report_type == "yearly" and year) else None
    resp = ReadingResponse(summary=summary, sections=sections, findings=findings,
                           disclaimers=DISCLAIMERS, meta=meta, varshphal=varshphal)
    if tier.cache:
        store.cache_put(ck, resp.model_dump())
    return resp
