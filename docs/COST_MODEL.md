# Cost, pricing & revenue analysis (FP&A)

Computed by `api/app/pricing.py`, enforced by `api/tests/test_pricing_gate.py`, and served
live at `GET /admin/economics`. Mid-2026 rates (verify quarterly): Gemini 2.5 Pro
$1.25/1M in, $10/1M out; Razorpay 2% + 18% GST on the fee; GST 18% on revenue; USD→INR 84.

## Executive summary
**Profitability is now gated by construction.** Two changes guarantee that run-cost can
never exceed revenue and that every paid tier holds **≥50% contribution margin** even at
100% utilization:

1. **All LLM cost is metered against one per-cycle allowance.** Previously chat was metered
   but **readings were not** - they cost Vertex tokens yet were bounded only by the daily
   call limit (e.g. Pro = 500 calls/day), an *unbounded* cost exposure. Now both readings
   and chat debit the same token allowance; **cached readings cost 0**. A user who exhausts
   the allowance gets `402` (upgrade / top-up). This caps per-user cost at the grant.
2. **Each tier's grant is gated to its price.** The grant is set ≤ `gated_grant_tokens(price)`,
   the largest allowance that still clears 50% margin at a conservative, output-heavy
   planning rate (₹0.00062/token). A CI test and a startup check fail if any tier drifts
   above its gate.

## The gate (per paying user, per cycle)
`net = price / 1.18` · `razorpay = price × 2% × 1.18` · `LLM budget = 0.5·net − razorpay`
· `gated grant = LLM budget / ₹0.00062`.

| tier | price | net (post-GST) | Razorpay | LLM budget | **gated grant** | **chosen grant** | worst-case margin |
|------|------:|---------------:|---------:|-----------:|----------------:|-----------------:|------------------:|
| Basic | ₹299 | ₹253 | ₹7.1 | ₹119.6 | 192,965 | **150,000** | **60.5%** ✅ |
| Pro | ₹999 | ₹847 | ₹23.6 | ₹399.7 | 644,723 | **600,000** | **53.3%** ✅ |
| Enterprise | ₹4999 | ₹4,236 | ₹118 | ₹2,000 | 3,226,199 | **3,000,000** | **53.3%** ✅ |

Chosen grants sit **below** the gate (headroom), so worst-case cost (₹93 / ₹372 / ₹1,860)
is well under both the budget and net revenue - **run-cost < revenue for every tier, always.**
*(Change from the previous plan: Basic 50k→150k and Pro 500k→600k became more generous;
Enterprise 5M→3M, because 5M exceeded its gate and could run at a loss.)*

## Sensitivity (does the gate survive rate shocks?)
The planning rate ₹0.00062/token already assumes output-heavy usage (≈3.4× the realistic
blended chat rate). The gate holds if, at worst case, `grant × actual_rate ≤ LLM budget`:

| shock | effect | still ≥50%? |
|-------|--------|-------------|
| Realistic blended use (~₹0.00032/tok) | cost ≈ half the planned | **Yes**, margins 70-80% |
| USD→INR 84 → 92 (+10%) | token cost +10% | Yes, headroom absorbs it; if not, re-run the gate |
| Gemini output price +20% | planning rate rises | Re-run `gated_grant_tokens`; trim grants if a tier un-gates (CI catches it) |

The single source of truth is `pricing.py`; bump the rate constants and the gate + tests
recompute. The startup check logs `PRICING GATE` if any tier exceeds its gate.

## Break-even (covering fixed cost)
Fixed baseline ≈ **₹2,600/mo** (Cloud Run scales to zero; Firestore/Hosting free-tier at
low volume; domain). Per-user **contribution** (net − Razorpay − worst-case LLM) is
≈ **₹153 (Basic) / ₹451 (Pro) / ₹2,258 (Enterprise)** at full use, higher at realistic use.
So the platform covers its fixed cost at roughly **17 Basic / 6 Pro / 2 Enterprise** paying
users, and every paying user beyond that is ≥50%-margin profit. Free users incur ~₹0 LLM
cost (chart-only, no LLM).

## Guardrails that keep it true
- `test_pricing_gate.py`: every paid tier ≥50% margin and cost < revenue at full use (CI gate).
- Startup `PRICING GATE` warning if a tier un-gates.
- Per-turn output cap, per-user daily token ceiling, and the **global daily spend breaker**
  bound absolute spend regardless of plan.
- Cache (readings keyed by chart + version) makes repeat readings free.
