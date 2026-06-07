"""Jyotish Cloud — a tiered, cloud-hosted Vedic astrology API.

Pipeline: birth details -> calculation engine (your code) -> deterministic
rules/findings -> constrained LLM renderer -> grounded reading.

The version stamps below are part of every cache key, so bumping any stage
(engine, rules, or renderer) safely invalidates previously cached readings.
"""

__version__ = "0.1.0"

# bump these when the corresponding stage's output changes
ENGINE_VERSION_FALLBACK = "mock-0.1"   # used only when the mock engine runs
RULES_VERSION = "rules-0.5"
RENDERER_VERSION = "render-0.3"
