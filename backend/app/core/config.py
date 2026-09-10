"""
Centralized settings, loaded from environment variables (.env locally,
Railway env vars in production — per Ghumi_TechStack.docx §4).

Add a new setting here the moment you add a new external service —
this file should always be the single place that knows what env vars exist.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    # --- Database / Auth (Supabase) ---
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_anon_key: str = ""
    database_url: str = ""  # Postgres connection string, via Supabase

    # --- LLM provider (Groq) ---
    groq_api_key: str = ""

    # --- External data APIs ---
    # Amadeus's self-service portal was decommissioned 2026-07-17 (Enterprise
    # API only now, not viable for this project) — replaced with Duffel
    # (flights) and LiteAPI (hotels). Hotelbeds was tried for hotels first
    # but its sandbox's very restrictive quota (a handful of calls before
    # "Quota exceeded") made it impractical for active development —
    # LiteAPI's sandbox allows 5 req/s, a genuinely usable limit.
    duffel_api_key: str = ""
    duffel_base_url: str = "https://api.duffel.com"
    liteapi_key: str = ""
    liteapi_base_url: str = "https://api.liteapi.travel/v3.0"
    google_places_api_key: str = ""

    # --- Observability ---
    langsmith_api_key: str = ""
    langsmith_project: str = "ghumi"
    langsmith_tracing: bool = True
    sentry_dsn: str = ""

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
