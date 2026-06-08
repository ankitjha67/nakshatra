"""Continuous fraud / abuse risk monitoring.

A TRANSPARENT, explainable risk model — a weighted sum of per-user signals, not a
black box — so every flag is auditable (you can see exactly which signals fired and
how many points each contributed). It is intentionally swappable: replace
`compute_risk` with a trained ML classifier later and every caller keeps working.

Two surfaces use it:
  * real-time   — `looks_malicious` blocks destructive chat the instant it arrives;
  * continuous  — `/internal/fraud-scan` (a scheduler cron) scores EVERY user, writes
                  a risk band, raises a warning banner, and auto-suspends the worst.
"""
from __future__ import annotations

import re

# Destructive / hacking intent (DB wipes, shell rm, SQLi, DoS). These NEVER occur in
# a genuine birth-chart question, so matching is high-precision -> block + escalate.
_MALICIOUS_RE = re.compile(
    r"\bdrop\s+(?:all\s+(?:the\s+)?)?(?:table|tables|database|databases|schema)\b"
    r"|\b(?:delete|truncate)\s+(?:from\s+\w+|all\s+(?:the\s+)?(?:data|tables|records|rows|users))\b"
    r"|\bdelete\s+(?:the\s+)?(?:whole\s+|entire\s+|all\s+(?:the\s+)?)?(?:database|data|records)\b"
    r"|\brm\s+-rf\b|\bformat\s+(?:the\s+)?(?:disk|drive|database|db)\b"
    r"|\b(?:shut\s*down|destroy|wipe|erase|nuke)\s+(?:the\s+)?(?:server|database|db|system|everything|all\s+data)\b"
    r"|(?:;|--)\s*drop\s+|\bunion\s+select\b|\bor\s+1\s*=\s*1\b|\b1\s*=\s*1\s*--"
    r"|\bsql\s*injection\b|\bxss\b|\bddos\b|\bransomware\b|\bmalware\b|\bkeylogger\b"
    r"|\b(?:hack|exploit|breach|compromise|pwn|takeover)\s+(?:the\s+)?(?:server|database|db|system|site|website|account|admin)\b",
    re.IGNORECASE,
)


def looks_malicious(text: str) -> bool:
    """Destructive/hacking intent (e.g. 'drop all the database'). Higher severity
    than a prompt-injection: block immediately AND weight heavily in the risk score."""
    return bool(_MALICIOUS_RE.search(text or ""))


# Generic, non-revealing refusal for destructive requests ("respond it can't do that").
MALICIOUS_REFUSAL = "I can't help with that. I can only discuss your birth chart and reading."

# Warning banners shown to flagged users (sent via /v1/me).
WATCH_BANNER = ("We've noticed unusual activity on your account and are reviewing it. "
                "Nakshatra is for genuine birth-chart readings, repeated policy "
                "violations may lead to suspension.")
HIGH_BANNER = ("Your account is flagged for suspicious activity and is under review. "
               "Further violations will result in suspension. If you believe this is "
               "a mistake, contact support.")


def risk_banner(band: str) -> str | None:
    return {"watch": WATCH_BANNER, "high": HIGH_BANNER}.get(band)


def compute_risk(user: dict, ctx: dict, settings) -> dict:
    """Score one user from their signals. `ctx` carries optionally-precomputed
    cross-user context (refunds, tokens_today, ip_accounts); missing keys = 0, so
    cheap per-request callers (e.g. /v1/me) can pass only what they have.

    Returns {score:0-100, band:'ok'|'watch'|'high', signals:[{signal,points,detail}]}.
    """
    user = user or {}
    ctx = ctx or {}
    mal = int(user.get("malicious_count") or 0)
    inj = int(user.get("jailbreak_count") or 0)
    refunds = int(ctx.get("refunds") or 0)
    tokens = int(ctx.get("tokens_today") or 0)
    ip_accounts = int(ctx.get("ip_accounts") or 0)

    signals: list[dict] = []

    def add(name: str, pts: int, detail: str) -> None:
        if pts > 0:
            signals.append({"signal": name, "points": int(pts), "detail": detail})

    add("malicious_intent", min(mal * 50, 100), f"{mal} destructive/hacking attempt(s)")
    add("injection_attempts", min(inj * 15, 60), f"{inj} prompt-injection/jailbreak attempt(s)")
    add("refund_abuse", min(refunds * 20, 60), f"{refunds} refund request(s)")
    if tokens >= getattr(settings, "anomaly_token_day_flag", 1_000_000):
        add("token_velocity", 30, f"{tokens:,} tokens today")
    if ip_accounts >= getattr(settings, "anomaly_ip_accounts_flag", 5):
        add("shared_ip", 25, f"{ip_accounts} accounts share one IP")

    score = min(sum(s["points"] for s in signals), 100)
    if score >= getattr(settings, "fraud_high_score", 75):
        band = "high"
    elif score >= getattr(settings, "fraud_watch_score", 40):
        band = "watch"
    else:
        band = "ok"
    return {"score": score, "band": band, "signals": signals}
