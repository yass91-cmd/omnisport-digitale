from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, make_url

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OMNI_", env_file=ROOT / ".env", extra="ignore")

    environment: str = "development"
    database_url: SecretStr | None = Field(default=None, repr=False)
    db_host: str = "127.0.0.1"
    db_port: int = Field(default=3307, ge=1, le=65535)
    db_name: str = "omnisport"
    db_user: str = "omnisport"
    db_password: SecretStr = Field(default=SecretStr(""), repr=False)
    auth_origins: list[str] = [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8001",
        "http://localhost:8001",
    ]
    cookie_secure: bool = False
    session_hours: int = Field(default=12, ge=1, le=24)
    session_idle_minutes: int = Field(default=30, ge=5, le=120)
    login_email_limit: int = Field(default=8, ge=1, le=100)
    login_ip_limit: int = Field(default=40, ge=1, le=500)
    kafka_bootstrap_servers: str = "kafka:19092"
    kafka_booking_topic: str = "booking-events.v1"
    kafka_dead_letter_topic: str = "booking-events.dlq"

    @model_validator(mode="after")
    def production_cookies(self):
        if self.environment == "production" and (
            not self.cookie_secure
            or any(not origin.startswith("https://") for origin in self.auth_origins)
        ):
            raise ValueError("Production requires secure cookies and explicit HTTPS auth origins")
        return self

    @property
    def session_cookie(self) -> str:
        return "__Host-omni_session" if self.cookie_secure else "omni_session"

    def sqlalchemy_url(self) -> URL:
        if self.database_url:
            return make_url(self.database_url.get_secret_value())
        if not self.db_password.get_secret_value():
            raise ValueError("Configure the environment with python scripts/configure.py")
        return URL.create(
            "mysql+pymysql",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        )
