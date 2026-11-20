from pathlib import Path

from pydantic import Field, SecretStr
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
