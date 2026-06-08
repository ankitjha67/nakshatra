"""Configuration via environment variables (12-factor).

Nothing here hard-codes a cloud vendor. Swap LLM_PROVIDER / STORE_BACKEND /
PAYMENTS_PROVIDER without touching application code. Secrets come from the
environment, which on GCP is wired to Secret Manager (see deploy/).
"""
from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- app ---
    app_env: str = "dev"
    log_level: str = "INFO"
    cors_origins: str = "*"          # comma-separated; tighten in prod

    # --- engine plug-in ---
    # Point these at YOUR Maha Jyotish module. The callable must accept a dict
    # of birth details and return a JSON-serialisable dict. If import fails,
    # the bundled mock engine runs so the service still boots.
    engine_module: str = ""          # e.g. "maha_jyotish.api"
    engine_callable: str = "compute_chart"
    engine_rectify_callable: str = "rectify_birth_time"   # BTR mode; mock-fallback if absent
    engine_version: str = ""         # report your engine's version here

    # --- LLM ---
    llm_provider: str = "mock"       # mock | anthropic | openai | vertex
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2500
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4"
    vertex_project: str = ""
    vertex_location: str = "asia-south1"
    vertex_model: str = "gemini-2.5-pro"

    # --- auth (Firebase / Google sign-in) ---
    firebase_project: str = ""        # defaults to firestore/vertex project if blank
    default_user_tier: str = "free"   # tier assigned to a user on first sign-in
    verify_token_revocation: bool = False   # check_revoked on ID tokens (recommend True in prod)
    require_email_verified: bool = False    # require a verified email before metered LLM access

    # --- store ---
    store_backend: str = "memory"    # memory | firestore | postgres
    firestore_project: str = ""
    database_url: str = ""           # postgres dsn when store_backend=postgres
    cache_readings: bool = True
    api_key_pepper: str = ""         # server pepper; B2B keys are stored hashed at rest
    persist_chat: bool = True        # store chat transcripts (set False to keep none)
    chat_retention_days: int = 0     # >0 stamps an expireAt for a Firestore TTL policy (0 = keep)

    # --- credits / chat metering (see docs/CREDIT_LEDGER.md) ---
    chat_max_output: int = 800             # hard per-turn output cap (bounded turn size)
    daily_token_ceiling: int = 200_000     # per-user/day abuse ceiling (independent of balance)
    daily_global_token_breaker: int = 0    # optional global daily Vertex spend breaker (0 = off)
    # abuse / anomaly thresholds (admin flagging)
    anomaly_token_day_flag: int = 1_000_000   # tokens/day above this flags a user
    anomaly_refund_flag: int = 3              # >= this many refund requests flags a user
    anomaly_ip_accounts_flag: int = 5         # >= this many accounts on one IP flags them
    anomaly_jailbreak_flag: int = 3           # >= this many jailbreak/injection attempts flags a user

    # --- auth / billing ---
    # No usable default: admin/internal endpoints stay disabled until a real
    # secret is configured (Secret Manager). Placeholders are rejected too.
    admin_api_key: str = ""                 # must be set (Secret Manager) to enable admin endpoints
    # Lock one native (person = date + place) per account after first use, so a
    # single subscription can't be used to read unlimited different people.
    birth_lock_enabled: bool = True
    # Cache retention: chart/reading caches hold birth-derived data; expire them so
    # PII ages out (enable a Firestore TTL policy on cache.expireAt). 0 = keep.
    cache_ttl_days: int = 90
    payments_provider: str = "none"        # none | razorpay | stripe
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    # per-tier recurring plan ids, "basic=plan_x,pro=plan_y,enterprise=plan_z"
    razorpay_plans: str = ""
    # optional per-tier discount offer ids (Razorpay Offers), "pro=offer_x,..."
    razorpay_offers: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # --- async ---
    # When set, /reading/async enqueues to Cloud Tasks instead of running in a
    # background thread. Leave blank for local/dev (runs in-process).
    cloud_tasks_queue: str = ""      # projects/.../locations/.../queues/...
    worker_base_url: str = ""        # public URL Cloud Tasks calls back to
    internal_token: str = ""             # must be set to enable the internal worker endpoint
    # optional outbound webhook for the scheduled metrics digest (Slack/Zapier/email relay)
    digest_webhook_url: str = ""


    @property
    def is_prod(self) -> bool:
        return self.app_env.lower() == "prod"

    @staticmethod
    def _parse_map(spec: str) -> dict:
        out: dict[str, str] = {}
        for part in (spec or "").split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() and v.strip():
                    out[k.strip()] = v.strip()
        return out

    def razorpay_plan_map(self) -> dict:
        return self._parse_map(self.razorpay_plans)

    def razorpay_offer_map(self) -> dict:
        return self._parse_map(self.razorpay_offers)

    def startup_warnings(self) -> list[str]:
        """Prod-readiness checks (logged at startup). Empty in dev."""
        if not self.is_prod:
            return []
        w: list[str] = []
        if self.admin_api_key in ("", "admin_dev_key", "change-me"):
            w.append("ADMIN_API_KEY is a default/placeholder, set a strong secret (Secret Manager).")
        if self.internal_token in ("", "internal_dev_token"):
            w.append("INTERNAL_TOKEN is the dev default, set a strong secret.")
        if self.cors_origins.strip() in ("", "*"):
            w.append("CORS_ORIGINS is '*' - lock it to the web origin in prod.")
        if self.store_backend == "memory":
            w.append("STORE_BACKEND=memory in prod, data is not persisted; use firestore.")
        if self.payments_provider != "none" and not (self.razorpay_webhook_secret or self.stripe_webhook_secret):
            w.append("payments enabled but no webhook secret set, signatures cannot be verified.")
        if self.llm_provider == "mock":
            w.append("LLM_PROVIDER=mock in prod, readings would be deterministic stubs, not real LLM output.")
        if self.daily_global_token_breaker <= 0:
            w.append("DAILY_GLOBAL_TOKEN_BREAKER is off (0), set a cap as a platform-wide spend backstop.")
        if not self.verify_token_revocation:
            w.append("VERIFY_TOKEN_REVOCATION is off, revoked/disabled sessions may still pass; enable in prod.")
        return w


@lru_cache
def get_settings() -> Settings:
    return Settings()
