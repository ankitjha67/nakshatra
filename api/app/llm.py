"""LLM layer — a constrained *writer*, never an interpreter.

The renderer hands the model a fixed set of computed findings and asks only for
prose. The system prompt forbids new placements/predictions, requires a citation
(finding code) behind every section, and bans horoscope filler, flattery, fear,
and medical/financial/legal directives. After generation we validate every
citation against the real finding codes and discard anything unsupported — so a
hallucinated claim cannot survive even if the model produces one.

Providers are pluggable. `mock` composes the reading deterministically from the
findings (zero external calls, zero slop) and is the default so the service runs
anywhere out of the box.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from .config import get_settings
from .models import Finding, ReadingSection
from . import RENDERER_VERSION

log = logging.getLogger("llm")

# ordered sections and which finding categories feed each
SECTION_SPEC: list[tuple[str, str, list[str]]] = [
    ("essence",       "Your Essence",            ["essence"]),
    ("mind",          "Mind & Emotions",         ["mind"]),
    ("relationships", "Love & Relationships",    ["relationships"]),
    ("career",        "Work & Direction",        ["career"]),
    ("wealth",        "Wealth & Resources",      ["wealth"]),
    ("family",        "Home & Family",           ["family"]),
    ("health",        "Health & Vitality",       ["health"]),
    ("timing",        "This Chapter — Timing",   ["timing"]),
    ("fortune",       "Fortune & Karma",         ["fortune"]),
    ("spirit",        "Inner Life",              ["spirit"]),
    ("strengths",     "Strengths & Stars",       ["strengths"]),
    ("kp",            "KP Insights",             ["kp"]),
    ("panchang",      "Birth Energy",            ["panchang"]),
    ("alerts",        "Sensitive Points",        ["alerts"]),
    ("numbers",       "Name & Numbers",          ["numbers"]),
    ("remedies",      "Supportive Practices",    ["remedies"]),
]

DISCLAIMERS = [
    "This reading is generated from your birth chart for reflection and guidance; it is not a prediction of fixed outcomes.",
    "It is not a substitute for medical, legal, financial, or psychological advice.",
]

SYSTEM_PROMPT = """You are the writer for a Vedic astrology (Jyotisha) service.

You are given a set of FINDINGS that were already computed from a person's birth chart, plus a list of SECTIONS to write. Your only job is to turn the findings into clear, warm, grounded prose.

ABSOLUTE RULES
- Use ONLY the information in the findings. Never introduce a planet, sign, house, nakshatra, yoga, dasha, aspect, date, or prediction that is not present in the findings you were given.
- Every section you write MUST list, in its "citations" array, the finding codes it is based on. Do not write a sentence that no finding supports.
- Plain and specific over vague. No generic horoscope filler ("the stars align", "trust the universe"), no flattery, no fear or doom, no absolute predictions.
- Never give medical, legal, financial, or psychological directives. Describe tendencies, not instructions.
- If the findings for a section are thin, write less. One honest sentence beats a paragraph of padding.
- Warm, literate, second person ("you"). Do not use the person's name. No emojis. No headings inside the body.

OUTPUT
Return STRICT JSON only, no markdown, matching:
{"summary": "2-3 sentence synthesis grounded in the highest-weight findings",
 "sections": [{"key": "<section key>", "body": "<prose>", "citations": ["<finding code>", ...]}]}
Only include sections you were asked to write and that have at least one supporting finding.

GOOD (grounded): {"key":"essence","body":"With a Libra ascendant ruled by Venus, you meet the world through balance and relationship; and because that ruler sits in your tenth house, the urge toward fairness shows up most in your work and public role.","citations":["LAGNA.SIGN","LAGNA.LORD"]}
BAD (invented placement, not in findings): "Your Mars in Aries makes you impulsive." (no such finding -> forbidden)
BAD (filler): "The cosmos has wonderful things in store for you." (cites nothing -> forbidden)"""


def _group(findings: list[Finding], allowed_keys: set[str]) -> list[dict[str, Any]]:
    out = []
    for key, title, cats in SECTION_SPEC:
        if key not in allowed_keys:
            continue
        fs = [f for f in findings if f.category in cats]
        if not fs:
            continue
        out.append({"key": key, "title": title,
                    "findings": [{"code": f.code, "title": f.title, "detail": f.detail} for f in fs]})
    return out


def _user_payload(chart_summary: str, sections: list[dict[str, Any]]) -> str:
    return json.dumps({"chart_summary": chart_summary, "sections_to_write": sections}, ensure_ascii=False)


def _chart_summary(findings: list[Finding]) -> str:
    top = findings[:4]
    return " ".join(f.detail for f in top)


# --------------------------------------------------------------------------- #
# providers
# --------------------------------------------------------------------------- #
class Provider:
    name = "base"
    model = None

    def render(self, system: str, user: str, payload: dict) -> tuple[dict, int, int]:
        raise NotImplementedError


class MockProvider(Provider):
    """Deterministic, grounded composition — no external call, no slop."""
    name = "mock"
    model = "mock-writer"

    def render(self, system, user, payload):
        sections = []
        for sec in payload["sections_to_write"]:
            bodies = [f["detail"] for f in sec["findings"]]
            body = " ".join(bodies)
            sections.append({"key": sec["key"], "body": body,
                             "citations": [f["code"] for f in sec["findings"]]})
        summary = payload.get("chart_summary", "").strip()
        return {"summary": summary, "sections": sections}, 0, 0


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, key: str, model: str, temp: float, max_tokens: int):
        import anthropic  # lazy
        self._c = anthropic.Anthropic(api_key=key)
        self.model = model; self.temp = temp; self.max_tokens = max_tokens

    def render(self, system, user, payload):
        r = self._c.messages.create(
            model=self.model, max_tokens=self.max_tokens, temperature=self.temp,
            system=system, messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return _parse_json(text), r.usage.input_tokens, r.usage.output_tokens


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, key: str, model: str, temp: float, max_tokens: int):
        from openai import OpenAI  # lazy
        self._c = OpenAI(api_key=key)
        self.model = model; self.temp = temp; self.max_tokens = max_tokens

    def render(self, system, user, payload):
        r = self._c.chat.completions.create(
            model=self.model, temperature=self.temp, max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        text = r.choices[0].message.content or "{}"
        u = r.usage
        return _parse_json(text), u.prompt_tokens, u.completion_tokens


class VertexProvider(Provider):
    name = "vertex"

    def __init__(self, project: str, location: str, model: str, temp: float, max_tokens: int):
        from google import genai  # lazy: google-genai
        self._c = genai.Client(vertexai=True, project=project, location=location)
        self.model = model; self.temp = temp; self.max_tokens = max_tokens

    def render(self, system, user, payload):
        from google.genai import types
        # Gemini 2.5 models "think" before answering and thinking tokens draw
        # from the output budget. For a constrained writing task we want minimal
        # thinking and plenty of room for the JSON, or it truncates to nothing.
        #   * 2.5 Pro: thinking cannot be 0 (min 128) -> cap at the floor.
        #   * 2.5 Flash / Lite: thinking can be disabled (0).
        cfg_kwargs = dict(
            system_instruction=system,
            temperature=self.temp,
            max_output_tokens=max(int(self.max_tokens), 8192),
            response_mime_type="application/json",
        )
        try:
            budget = 128 if "pro" in (self.model or "").lower() else 0
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=budget)
        except Exception:  # SDK without ThinkingConfig — proceed without it
            pass

        r = self._c.models.generate_content(
            model=self.model, contents=user,
            config=types.GenerateContentConfig(**cfg_kwargs),
        )
        text = r.text or "{}"
        um = getattr(r, "usage_metadata", None)
        ti = getattr(um, "prompt_token_count", 0) or 0
        to = getattr(um, "candidates_token_count", 0) or 0
        if not text or text.strip() in ("", "{}"):
            cand = (getattr(r, "candidates", None) or [None])[0]
            log.warning("Vertex returned empty text (finish_reason=%s, out_tokens=%s)",
                        getattr(cand, "finish_reason", "?"), to)
        return _parse_json(text), ti, to


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else {"summary": "", "sections": []}


_PROVIDER: Provider | None = None


def get_provider() -> Provider:
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    s = get_settings()
    try:
        if s.llm_provider == "anthropic" and s.anthropic_api_key:
            _PROVIDER = AnthropicProvider(s.anthropic_api_key, s.anthropic_model, s.llm_temperature, s.llm_max_tokens)
        elif s.llm_provider == "openai" and s.openai_api_key:
            _PROVIDER = OpenAIProvider(s.openai_api_key, s.openai_model, s.llm_temperature, s.llm_max_tokens)
        elif s.llm_provider == "vertex" and s.vertex_project:
            _PROVIDER = VertexProvider(s.vertex_project, s.vertex_location, s.vertex_model, s.llm_temperature, s.llm_max_tokens)
        else:
            _PROVIDER = MockProvider()
    except Exception as exc:  # noqa: BLE001 — never fail the request on provider init
        log.error("LLM provider init failed (%s); using mock.", exc)
        _PROVIDER = MockProvider()
    log.info("LLM provider: %s (%s)", _PROVIDER.name, _PROVIDER.model)
    return _PROVIDER


# --------------------------------------------------------------------------- #
# renderer
# --------------------------------------------------------------------------- #
def render_reading(chart: dict, findings: list[Finding], allowed_sections: set[str]
                   ) -> tuple[str, list[ReadingSection], str, int, int]:
    """Return (summary, sections, model_name, tokens_in, tokens_out)."""
    sections_payload = _group(findings, allowed_sections)
    summary_seed = _chart_summary(findings)
    user = _user_payload(summary_seed, sections_payload)
    provider = get_provider()
    try:
        data, ti, to = provider.render(SYSTEM_PROMPT, user, {"chart_summary": summary_seed,
                                                             "sections_to_write": sections_payload})
    except Exception as exc:  # noqa: BLE001
        log.error("LLM render failed (%s); using deterministic fallback.", exc)
        data, ti, to = MockProvider().render(SYSTEM_PROMPT, user,
                                              {"chart_summary": summary_seed,
                                               "sections_to_write": sections_payload})

    valid_codes = {f.code for f in findings}
    title_by_key = {k: t for k, t, _ in SECTION_SPEC}
    out_sections: list[ReadingSection] = []
    for sec in data.get("sections", []):
        key = sec.get("key")
        if key not in allowed_sections or key not in title_by_key:
            continue
        cites = [c for c in sec.get("citations", []) if c in valid_codes]  # drop hallucinated cites
        body = (sec.get("body") or "").strip()
        if not body:
            continue
        out_sections.append(ReadingSection(key=key, title=title_by_key[key], body=body, citations=cites))

    # keep section order stable per SECTION_SPEC
    order = {k: i for i, (k, _, _) in enumerate(SECTION_SPEC)}
    out_sections.sort(key=lambda s: order.get(s.key, 99))
    summary = (data.get("summary") or summary_seed).strip()
    return summary, out_sections, provider.model or provider.name, ti, to
