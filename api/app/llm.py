"""LLM layer, a constrained *writer*, never an interpreter.

The renderer hands the model a fixed set of computed findings and asks only for
prose. The system prompt forbids new placements/predictions, requires a citation
(finding code) behind every section, and bans horoscope filler, flattery, fear,
and medical/financial/legal directives. After generation we validate every
citation against the real finding codes and discard anything unsupported, so a
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
    ("yearly",        "The Year, Varshphal",    ["yearly"]),
    ("prashna",       "The Question, KP Verdict", ["prashna"]),
    ("btr",           "Birth-Time Rectification", ["btr"]),
    ("essence",       "Your Essence",            ["essence"]),
    ("mind",          "Mind & Emotions",         ["mind"]),
    ("relationships", "Love & Relationships",    ["relationships"]),
    ("career",        "Work & Direction",        ["career"]),
    ("wealth",        "Wealth & Resources",      ["wealth"]),
    ("family",        "Home & Family",           ["family"]),
    ("health",        "Health & Vitality",       ["health"]),
    ("timing",        "This Chapter, Timing",   ["timing"]),
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


# Common words the mock chat must NOT treat as chart keywords (keeps the
# deterministic fallback honest; the real LLM does its own grounding).
_CHAT_STOPWORDS = {
    "about", "what", "does", "tell", "with", "from", "this", "that", "they", "them",
    "have", "will", "would", "could", "should", "your", "yours", "mine", "more",
    "much", "when", "where", "which", "into", "like", "some", "very", "just", "than",
    "then", "there", "here", "also", "each", "other", "over", "under",
    # meta words about asking, not chart topics
    "chart", "charts", "say", "says", "said", "mean", "means", "show", "shows",
    "anything", "something", "everything", "know", "give", "want", "please",
}

# Grounded chat: the model answers follow-ups ONLY from the user's findings.
CHAT_SYSTEM_PROMPT = """You are a careful Vedic astrology (Jyotisha) assistant answering a user's follow-up questions about THEIR OWN birth chart.

You are given FINDINGS already computed from this user's chart, the recent conversation, and a new question.

ABSOLUTE RULES
- Answer ONLY from the FINDINGS. If the findings do not address the question, say so plainly, do not guess or invent.
- Never introduce a planet, sign, house, nakshatra, yoga, dasha, aspect, date, or prediction that is not in the findings.
- No generic horoscope filler, no flattery, no fear or doom, no absolute predictions.
- Never give medical, legal, financial, or psychological directives. Describe tendencies, not instructions.
- Warm, literate, second person ("you"). Brief and specific, a few sentences. Do not use the person's name. No emojis. No headings."""


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

    def chat(self, system: str, user: str, max_output: int) -> tuple[str, int, int]:
        """Free-text grounded answer. Returns (text, tokens_in, tokens_out)."""
        raise NotImplementedError


class MockProvider(Provider):
    """Deterministic, grounded composition, no external call, no slop."""
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

    def chat(self, system, user, max_output):
        """Deterministic, grounded answer composed from the findings in `user`.
        Estimates tokens (~4 chars/token) so local/dev metering is non-zero."""
        try:
            data = json.loads(user)
        except Exception:
            data = {}
        findings = data.get("findings", [])
        q = (data.get("question") or "").lower()
        words = set(re.findall(r"[a-z]{4,}", q)) - _CHAT_STOPWORDS

        def score(f):
            text = (str(f.get("title", "")) + " " + str(f.get("detail", ""))).lower()
            return sum(1 for w in words if w in text)

        best = [f for f in sorted(findings, key=score, reverse=True) if score(f) > 0][:2]
        if best:
            answer = "From your chart: " + " ".join(f.get("detail", "") for f in best)
        elif findings:
            topics = ", ".join(sorted({f.get("title", "") for f in findings})[:4])
            answer = ("Your chart's findings don't directly speak to that. They do cover: "
                      f"{topics}. Ask about one of those and I can ground an answer in your chart.")
        else:
            answer = "I don't have computed findings for your chart yet, cast a reading first."
        ti = (len(system) + len(user)) // 4
        to = max(1, len(answer) // 4)
        return answer, ti, to


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

    def chat(self, system, user, max_output):
        r = self._c.messages.create(
            model=self.model, max_tokens=max(int(max_output), 64), temperature=self.temp,
            system=system, messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return text, r.usage.input_tokens, r.usage.output_tokens


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

    def chat(self, system, user, max_output):
        r = self._c.chat.completions.create(
            model=self.model, temperature=self.temp, max_tokens=max(int(max_output), 64),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        text = r.choices[0].message.content or ""
        u = r.usage
        return text, u.prompt_tokens, u.completion_tokens


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
        except Exception:  # SDK without ThinkingConfig, proceed without it
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

    def chat(self, system, user, max_output):
        from google.genai import types
        # Free-text (not JSON). Hard per-turn output cap bounds the turn size.
        cfg_kwargs = dict(
            system_instruction=system,
            temperature=self.temp,
            max_output_tokens=max(int(max_output), 64),
        )
        try:
            budget = 128 if "pro" in (self.model or "").lower() else 0
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=budget)
        except Exception:
            pass
        r = self._c.models.generate_content(
            model=self.model, contents=user,
            config=types.GenerateContentConfig(**cfg_kwargs),
        )
        text = r.text or ""
        um = getattr(r, "usage_metadata", None)
        ti = getattr(um, "prompt_token_count", 0) or 0
        to = getattr(um, "candidates_token_count", 0) or 0
        return text, ti, to


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
    except Exception as exc:  # noqa: BLE001, never fail the request on provider init
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


# --------------------------------------------------------------------------- #
# grounded chat (Phase 5), answers ONLY from the user's findings
# --------------------------------------------------------------------------- #
def _chat_payload(findings: list[Finding], history: list[dict], message: str) -> str:
    return json.dumps({
        "findings": [{"code": f.code, "title": f.title, "detail": f.detail} for f in findings],
        "history": [{"role": m.get("role"), "text": m.get("text")} for m in history][-8:],
        "question": message,
    }, ensure_ascii=False)


def chat_answer(findings: list[Finding], history: list[dict], message: str,
                max_output: int) -> tuple[str, str, int, int]:
    """Return (answer, model_name, tokens_in, tokens_out). Grounded in findings."""
    provider = get_provider()
    user = _chat_payload(findings, history, message)
    try:
        answer, ti, to = provider.chat(CHAT_SYSTEM_PROMPT, user, max_output)
    except Exception as exc:  # noqa: BLE001, never fail the request on provider error
        log.error("chat render failed (%s); using deterministic mock.", exc)
        answer, ti, to = MockProvider().chat(CHAT_SYSTEM_PROMPT, user, max_output)
    return (answer or "").strip(), provider.model or provider.name, ti, to
