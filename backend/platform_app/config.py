import json
from functools import lru_cache
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    environment: str = "development"
    database_url: SecretStr = SecretStr("sqlite:///./platform.db")
    system_database_url: SecretStr | None = None
    redis_url: SecretStr | None = None
    master_bot_token: SecretStr = SecretStr("")
    master_webhook_secret: SecretStr = SecretStr("")
    master_bot_username: str = ""
    platform_owner_ids: str = ""
    encryption_keys: SecretStr = SecretStr("{}")
    active_key_version: str = "v1"
    public_api_url: str = "http://localhost:8000"
    mini_app_url: str = "http://localhost:3000"
    allowed_origins: str = "http://localhost:3000"
    session_ttl_seconds: int = 1800
    init_data_max_age_seconds: int = 300
    trial_days: int = 7
    storage_path: str = "./storage"
    max_upload_bytes: int = 5 * 1024 * 1024
    telegram_test_environment: bool = False
    demo_enabled: bool = False
    worker_lease_seconds: int = 180
    jobs_per_tenant_round: int = 5
    bot_rps: int = 20
    tenant_rps: int = 30
    global_rps: int = 300
    user_rps: int = 1

    @property
    def owner_ids(self) -> set[int]:
        return {int(x.strip()) for x in self.platform_owner_ids.split(",") if x.strip()}

    @model_validator(mode="after")
    def production_guard(self):
        if self.environment == "production":
            if self.demo_enabled or not self.database_url.get_secret_value().startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL and demo disabled")
            if not self.system_database_url or not self.redis_url:
                raise ValueError("Production requires distinct system database role and Redis")
            if self.system_database_url == self.database_url:
                raise ValueError("API and system database credentials must differ")
            if not self.public_api_url.startswith("https://") or not self.mini_app_url.startswith("https://"):
                raise ValueError("Production requires HTTPS URLs")
            if (
                not self.master_bot_token.get_secret_value()
                or len(self.master_webhook_secret.get_secret_value()) < 32
            ):
                raise ValueError("Master credentials are required")
            if not json.loads(self.encryption_keys.get_secret_value()):
                raise ValueError("Encryption keyring is required")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
