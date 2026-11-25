"""Runtime configuration loaded from environment variables (prefix ``STOCKS_``)."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STOCKS_", env_file=".env", extra="ignore")

    mongo_url: str = Field(..., description="MongoDB connection string; must point at a replica set")
    mongo_db: str = "stocks"
    # Comma-separated list of accepted API keys. The API refuses to start without at least one.
    api_keys: str = ""
    # Website login: a secret sign-in link (/login/<login_token>, bookmarkable) and/or a password.
    # With neither set, the website pages respond 503 with setup instructions (the API still works).
    login_token: str = ""
    admin_password: str = ""
    # Signs the website session cookie; required when either login method is set.
    session_secret: str = ""
    # Session cookie is sent only over HTTPS. Set STOCKS_SESSION_HTTPS_ONLY=false only for local HTTP development.
    session_https_only: bool = True
    # The website's address (scheme and host only). Passkeys are bound to it. Railway's own public domain is
    # used when unset; with neither, passkeys are disabled and the sign-in link still works.
    public_url: str = ""
    railway_public_domain: str = Field(default="", validation_alias="RAILWAY_PUBLIC_DOMAIN")
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

    @field_validator("public_url")
    @classmethod
    def _origin(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v:
            return ""
        u = urlsplit(v)
        if not u.hostname or v != f"{u.scheme}://{u.netloc}" or u.username is not None \
                or not (u.scheme == "https" or (u.scheme == "http" and u.hostname == "localhost")):
            raise ValueError("STOCKS_PUBLIC_URL must be https://<host> with no path (http only for localhost)")
        return v.lower()

    def passkey_origin(self) -> str:
        """The origin passkeys are bound to, or "" when passkeys are disabled."""
        if self.public_url:
            return self.public_url
        return f"https://{self.railway_public_domain.lower()}" if self.railway_public_domain else ""

    def api_key_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
