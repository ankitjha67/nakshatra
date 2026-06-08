"""Jyotish Cloud, a tiered, cloud-hosted Vedic astrology API.

Pipeline: birth details -> calculation engine (your code) -> deterministic
rules/findings -> constrained LLM renderer -> grounded reading.

The version stamps below are part of every cache key, so bumping any stage
(engine, rules, or renderer) safely invalidates previously cached readings.
"""

__version__ = "0.1.0"

# bump these when the corresponding stage's output changes
ENGINE_VERSION_FALLBACK = "mock-0.3"   # mock-0.3: + yogi/avayogi, bhrigu bindu, double transit, dasha balance
RULES_VERSION = "rules-0.9"       # 0.8: finer evidence; 0.9: extend to wealth/family/9th/12th/yogas + ashtakavarga, tier-gate divisional/KP/AV evidence
RENDERER_VERSION = "render-0.9"   # 0.4: report_type; 0.5: yearly; 0.6: prashna; 0.7: btr; 0.8: light/shadow + verdict; 0.9: evidence in prompt + specificity mandate
