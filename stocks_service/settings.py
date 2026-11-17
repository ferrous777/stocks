"""Runtime configuration loaded from environment variables (prefix ``STOCKS_``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STOCKS_", env_file=".env", extra="ignore")

    mongo_url: str = Field(..., description="MongoDB connection string; must point at a replica set")
    mongo_db: str = "stocks"
    # Comma-separated list of accepted API keys. The API refuses to start without at least one.
    api_keys: str = ""
    # Website login. When unset, the website pages respond 503 with setup instructions (the API still works).
    admin_password: str = ""
    # Signs the website session cookie; required when admin_password is set.
    session_secret: str = ""
    # Session cookie is sent only over HTTPS. Set STOCKS_SESSION_HTTPS_ONLY=false only for local HTTP development.
    session_https_only: bool = True
    # Bars are only treated as complete once their end time is this far in the past,
    # giving the data source time to finalize them.
    ingest_buffer_minutes: int = 20
    yahoo_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    yahoo_timeout_seconds: float = 30.0
    # Raw overnight move (|log(open/prev_close)|) above which a daily bar with no
    # corporate action on file quarantines the symbol for manual review.
    unexplained_gap_log_threshold: float = 0.47  # ~ +60% / -37%
    # Relative close difference tolerated between a re-fetched bar and the stored bar.
    overlap_tolerance: float = 0.005

    @field_validator("api_keys")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    def api_key_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
