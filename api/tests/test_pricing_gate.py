"""Profit gate: every paid tier must be guaranteed >=50% margin at full utilization.

This is the financial invariant the FP&A model enforces, if someone edits a tier's
price or grant into a loss-making combination, CI fails here.
"""
from app import pricing
from app.billing import TIERS

GST = 0.18
RZP = 0.02


def test_all_paid_tiers_are_profit_gated():
    for k, t in TIERS.items():
        if not t.monthly_tokens:
            continue
        gate = pricing.gated_grant_tokens(t.price_inr_month)
        assert pricing.tier_is_gated(t.price_inr_month, t.monthly_tokens), (
            f"{k}: grant {t.monthly_tokens:,} exceeds 50%-margin gate {gate:,}")


def test_worst_case_margin_at_least_50pct():
    for k, t in TIERS.items():
        if not t.monthly_tokens:
            continue
        net = t.price_inr_month / (1 + GST)
        razorpay = t.price_inr_month * RZP * (1 + GST)
        worst_cost = t.monthly_tokens * pricing.PLAN_INR_PER_TOKEN
        margin = (net - razorpay - worst_cost) / net
        assert margin >= 0.50, f"{k}: worst-case margin {margin:.1%} < 50%"


def test_worst_case_cost_below_revenue():
    # run-cost must never exceed revenue, for every tier, even fully used
    for k, t in TIERS.items():
        if not t.monthly_tokens:
            continue
        net = t.price_inr_month / (1 + GST)
        worst_cost = t.monthly_tokens * pricing.PLAN_INR_PER_TOKEN
        assert worst_cost < net, f"{k}: cost {worst_cost:.0f} >= net revenue {net:.0f}"
