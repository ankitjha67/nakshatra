"""Request/response schemas + the canonical hash used for caching.

A natal chart is deterministic in (date, time, tz, lat, lon, ayanamsa, house
system). We hash exactly those fields so identical birth data reuses a cached
chart/reading and costs no LLM tokens. The person's name is deliberately
excluded from the chart/reading substance (it doesn't change the sky), which
keeps cache hit-rates high; greet by name in the UI layer instead.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #
class BirthDetails(BaseModel):
    name: Optional[str] = Field(None, max_length=80, description="For greeting only; not used in the reading body")
    date: str = Field(..., description="Birth date, YYYY-MM-DD")
    time: str = Field(..., description="Birth time 24h, HH:MM (local to tz)")
    tz: str = Field("+05:30", max_length=40, description="UTC offset like +05:30 or IANA zone")
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    place: Optional[str] = Field(None, max_length=120, description="Human-readable place (optional)")
    ayanamsa: str = Field("lahiri", description="Ayanamsa system")
    house_system: str = Field("whole_sign", description="House system")
    # Reading-only: which report to render. Deliberately excluded from chart_hash
    # (it doesn't change the sky) but it IS part of the reading cache key.
    # /v1/chart ignores it.
    report_type: Literal["natal", "maha_kundali", "yearly"] = "maha_kundali"
    # Target calendar year for report_type="yearly" (Varshphal). Ignored otherwise.
    # Also excluded from chart_hash; added to the reading cache key for yearly.
    year: Optional[int] = Field(None, ge=1900, le=2200, description="Year for report_type=yearly")

    @field_validator("date")
    @classmethod
    def _date_ok(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError("date must be YYYY-MM-DD")
        return v

    @field_validator("time")
    @classmethod
    def _time_ok(cls, v: str) -> str:
        if not re.fullmatch(r"\d{2}:\d{2}", v):
            raise ValueError("time must be HH:MM (24h)")
        return v

    def canonical(self) -> str:
        return "|".join([
            self.date, self.time, self.tz.strip(),
            f"{self.lat:.4f}", f"{self.lon:.4f}",
            self.ayanamsa.lower(), self.house_system.lower(),
        ])

    def chart_hash(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()[:32]


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
class Meta(BaseModel):
    engine_version: str
    rules_version: Optional[str] = None
    renderer_version: Optional[str] = None
    model: Optional[str] = None
    tier: Optional[str] = None
    report_type: Optional[str] = None
    year: Optional[int] = None
    cache_hit: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    chart_hash: Optional[str] = None


class ChartResponse(BaseModel):
    chart: dict[str, Any]
    meta: Meta


class Finding(BaseModel):
    code: str                                   # stable id, e.g. "DIG.JUP.EXALT"
    category: str                               # essence|mind|relationships|career|wealth|health|timing|spirit
    polarity: Literal["supportive", "challenging", "mixed", "neutral"] = "neutral"
    weight: int = 1                             # ranking importance (1-10)
    title: str
    detail: str                                 # factual, jyotish-correct sentence (the ground truth)
    evidence: list[str] = []                    # ["Jupiter in Cancer (exalted), 5th house"]


class ReadingSection(BaseModel):
    key: str
    title: str
    body: str
    citations: list[str] = []                   # finding codes this section is grounded in


class ReadingResponse(BaseModel):
    summary: str
    sections: list[ReadingSection]
    findings: list[Finding]                     # the evidence behind the prose (shown for trust)
    disclaimers: list[str]
    meta: Meta


class JobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "error"]
    result: Optional[ReadingResponse] = None
    error: Optional[str] = None
