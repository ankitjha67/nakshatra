"""Unit economics & cost model, configurable, so it stays correct as rates move.

All rates are overridable via env (Settings) but ship with mid-2026 defaults:
  - Gemini 2.5 Pro: $1.25 / 1M input tokens, $10 / 1M output tokens.
  - Razorpay: 2% platform fee + 18% GST on the fee  (~2.36% effective).
  - GST on revenue: 18% (price treated as GST-inclusive; business remits the GST).
  - USD->INR ~ 84.

Used by /admin/economics and COST_MODEL.md. Cost is driven by *actual* tokens
consumed, so margins improve as utilization drops below the monthly grant.
"""
from __future__ import annotations

from dataclasses import dataclass

# --- rates (mid-2026 defaults) ---
USD_INR = 84.0
GEMINI_IN_USD_PER_1M = 1.25
GEMINI_OUT_USD_PER_1M = 10.0
RAZORPAY_FEE_PCT = 0.02
GST_PCT = 0.18

# --- usage assumptions (tokens per unit of work) ---
READING_IN, READING_OUT = 8_000, 8_000     # a full Maha-Kundali reading (uncached)
CHAT_IN, CHAT_OUT = 2_000, 800             # a typical chat turn (output is capped)

# --- fixed monthly infrastructure (INR), low-traffic baseline ---
# Cloud Run scales to zero; Firestore/Hosting largely free-tier at low volume.
FIXED_MONTHLY_INR = 2_500.0
DOMAIN_MONTHLY_INR = 100.0                  # ~₹1,200/yr


def _inr(tin: int, tout: int) -> float:
    usd = tin / 1e6 * GEMINI_IN_USD_PER_1M + tout / 1e6 * GEMINI_OUT_USD_PER_1M
    return usd * USD_INR


def reading_cost_inr() -> float:
    return _inr(READING_IN, READING_OUT)


def chat_inr_per_token() -> float:
    """Blended INR cost per chat token, using the assumed in:out split."""
    total = CHAT_IN + CHAT_OUT
    return _inr(CHAT_IN, CHAT_OUT) / total if total else 0.0


@dataclass
class TierEconomics:
    tier: str
    price_inr: int
    net_revenue_inr: float        # after GST remittance
    razorpay_inr: float
    token_cost_inr: float         # chat (at utilization) + readings
    variable_cost_inr: float
    margin_pct: float             # before fixed infra
    price_for_50pct_inr: float    # price needed for a 50% margin at this usage


def tier_economics(tier_key: str, price_inr: int, monthly_tokens: int,
                   utilization: float = 1.0, readings_per_month: int = 30,
                   target_margin: float = 0.5) -> TierEconomics:
    net = price_inr / (1 + GST_PCT)
    razorpay = price_inr * RAZORPAY_FEE_PCT * (1 + GST_PCT)
    tokens = monthly_tokens * utilization
    token_cost = tokens * chat_inr_per_token() + readings_per_month * reading_cost_inr()
    variable = razorpay + token_cost
    margin = (net - variable) / net if net else 0.0
    # price s.t. (price/1.18 - razorpay(price) - token_cost) / (price/1.18) = target
    # price/1.18*(1-target) = token_cost + price*0.0236  ->  solve for price
    k = (1 - target_margin) / (1 + GST_PCT) - RAZORPAY_FEE_PCT * (1 + GST_PCT)
    price_for_target = token_cost / k if k > 0 else float("inf")
    return TierEconomics(tier_key, price_inr, round(net, 2), round(razorpay, 2),
                         round(token_cost, 2), round(variable, 2), round(margin * 100, 1),
                         round(price_for_target, 0))


# Conservative, output-heavy PLANNING rate (₹/token) used to GATE tier grants so a
# worst-case (full-utilization, output-skewed) cycle still clears the margin target.
# Higher than the realistic blended rate on purpose, the gate must not under-protect.
PLAN_INR_PER_TOKEN = 0.00062     # ~30% input / 70% output at $1.25/$10 per 1M, ₹/$ 84


def monthly_llm_budget_inr(price_inr: int, target_margin: float = 0.5) -> float:
    """Max LLM spend per cycle (readings + chat) that still leaves `target_margin`
    after GST and Razorpay. This is the hard cost ceiling per paying user."""
    net = price_inr / (1 + GST_PCT)
    razorpay = price_inr * RAZORPAY_FEE_PCT * (1 + GST_PCT)
    return net * (1 - target_margin) - razorpay


def gated_grant_tokens(price_inr: int, target_margin: float = 0.5) -> int:
    """The largest monthly token grant a tier can offer at `price_inr` and still
    hold `target_margin` at full utilization (conservative planning rate)."""
    budget = monthly_llm_budget_inr(price_inr, target_margin)
    return int(max(0.0, budget) / PLAN_INR_PER_TOKEN)


def tier_is_gated(price_inr: int, monthly_tokens: int, target_margin: float = 0.5) -> bool:
    """True if this (price, grant) pair is guaranteed >= target_margin at worst case."""
    return monthly_tokens <= gated_grant_tokens(price_inr, target_margin)


def monthly_platform_cost(active_users: int, avg_utilization: float = 0.3,
                          avg_monthly_tokens: int = 500_000, avg_readings: int = 20) -> dict:
    """Projected monthly run cost (INR) at a given active-user count."""
    per_user_tokens = avg_monthly_tokens * avg_utilization
    variable = active_users * (per_user_tokens * chat_inr_per_token() + avg_readings * reading_cost_inr())
    fixed = FIXED_MONTHLY_INR + DOMAIN_MONTHLY_INR
    return {"active_users": active_users, "fixed_inr": round(fixed, 2),
            "variable_inr": round(variable, 2), "total_inr": round(fixed + variable, 2)}
