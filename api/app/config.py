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

    # --- store ---
    store_backend: str = "memory"    # memory | firestore | postgres
    firestore_project: str = ""
    database_url: str = ""           # postgres dsn when store_backend=postgres
    cache_readings: bool = True

    # --- auth / billing ---
    admin_api_key: str = "admin_dev_key"   # CHANGE in prod; provisions keys
    payments_provider: str = "none"        # none | razorpay | stripe
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # --- async ---
    # When set, /reading/async enqueues to Cloud Tasks instead of running in a
    # background thread. Leave blank for local/dev (runs in-process).
    cloud_tasks_queue: str = ""      # projects/.../locations/.../queues/...
    worker_base_url: str = ""        # public URL Cloud Tasks calls back to
    internal_token: str = "internal_dev_token"  # guards the worker endpoint


@lru_cache
def get_settings() -> Settings:
    return Settings()
