# Legal documents — Nakshatra

Major-site-grade **templates**, tailored to this product (India + GDPR, astrology
disclaimers, Razorpay, token credits). They are starting points, **not legal advice** —
have a qualified lawyer review and finalize them, fill every `[bracketed]` placeholder,
and set effective dates before launch.

- [Terms of Service](TERMS_OF_SERVICE.md) — eligibility, subscriptions/auto-renewal, token
  credits, acceptable use, fraud/bans, disclaimers, liability, governing law.
- [Privacy Policy](PRIVACY_POLICY.md) — data collected (incl. birth details, IP, chat),
  purposes/legal bases, sub-processors (Google/Vertex/Razorpay), retention, DSAR rights
  (wired to `/v1/me/export` and `DELETE /v1/me`), Grievance Officer.
- [Refund & Cancellation Policy](REFUND_POLICY.md) — subscription cancel/refund window,
  top-up (consumed = non-refundable), how to request (`/v1/refunds`), processing time.
- [Copyright & IP Notice](COPYRIGHT.md) — ownership of the engine/brand, your-content
  license, takedown process.

**To go live:** (1) lawyer review; (2) fill placeholders + dates; (3) publish as rendered
pages and link them from the site footer and the checkout/sign-up flow (with explicit
acceptance). The DSAR endpoints and the abuse/ban controls referenced here are already
implemented in the API.
