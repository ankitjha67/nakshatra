# Cost model & unit economics

Computed by `api/app/pricing.py` (configurable rates) and served live at
`GET /admin/economics`. Figures below use **mid-2026 rates** (verify before launch):
Gemini 2.5 Pro $1.25/1M in, $10/1M out; Razorpay 2% + 18% GST; GST 18% on revenue;
USD→INR 84. **Cost is driven by *actual* tokens used**, so real margins are higher
than the full-utilization worst case.

## Unit costs
- **One uncached Maha-Kundali reading:** ~₹7.6 in Gemini tokens (readings are cached,
  so repeats cost ₹0).
- **Chat:** ~₹0.315 per 1,000 tokens (blended in/out).

## Per-tier margin (price is GST-inclusive; before fixed infra)
| tier | price | net (post-GST) | Razorpay | token+reading cost | **margin** | price for 50% |
|------|------:|---------------:|---------:|-------------------:|-----------:|--------------:|
| **Worst case — full grant used + 30 readings/mo** ||||||
| basic | ₹299 | ₹253 | ₹7.1 | ₹242.6 | **1.5%** ⚠️ | ₹606 |
| pro | ₹999 | ₹847 | ₹23.6 | ₹384.3 | **51.8%** ✅ | ₹960 |
| enterprise | ₹4999 | ₹4236 | ₹118 | ₹1801.8 | **54.7%** ✅ | ₹4503 |
| **Realistic — 30% utilization + 15 readings/mo** ||||||
| basic | ₹299 | — | — | ₹118 | **50.6%** ✅ | — |
| pro | ₹999 | — | — | ₹161 | **78.2%** ✅ | — |
| enterprise | ₹4999 | — | — | ₹586 | **83.4%** ✅ | — |

### ⚠️ Finding: Basic tier is unprofitable at high utilization
At ₹299 with a 50,000-token monthly chat grant, a power user who uses the **full** grant
collapses Basic to **~1.5% margin** (≈₹606 would be needed for 50%). Pro and Enterprise
hold ≥50% even fully used. **Recommendation (pick one):** cut Basic's chat grant to
~20,000 tokens, and/or raise Basic to ~₹399–₹599, and/or cap free readings per cycle.
The `daily_token_ceiling` + per-turn cap already bound the absolute downside, but the
grant/price should be tuned so Basic is structurally ≥50%.

## Monthly platform run-cost (at 30% util, ~500k-token-equiv, 20 readings/user)
| active users | fixed | variable (tokens) | **total / month** |
|-------------:|------:|------------------:|------------------:|
| 100 | ₹2,600 | ₹19,845 | **~₹22,400** |
| 1,000 | ₹2,600 | ₹198,450 | **~₹2.0 L** |
| 10,000 | ₹2,600 | ₹1,984,500 | **~₹19.9 L** |

- **Fixed baseline ≈ ₹2,600/mo** (Cloud Run scales to zero; Firestore/Hosting largely
  free-tier at low volume; domain ~₹100/mo). It stays small; **token spend dominates** as
  you grow — which is why server-side metering, the per-user ceiling, and the **global
  daily spend breaker** matter.
- These are *gross* run-costs; they're more than covered by tier revenue at the margins
  above (token cost is also what each tier's price is sized against).

## Levers to protect margin
1. **Cache** readings aggressively (already keyed by chart + version) — repeat readings are free.
2. **Right-size grants** (esp. Basic) so full utilization still yields ≥50%.
3. **Batch API** (−50% on async) for non-interactive readings.
4. Keep **`DAILY_GLOBAL_TOKEN_BREAKER`** set so a spike can't blow the monthly budget.
5. Revisit rates quarterly — `pricing.py` constants are the single source of truth.
