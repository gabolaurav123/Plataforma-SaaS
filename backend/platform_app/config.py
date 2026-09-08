import json
from functools import lru_cache
from typing import Literal
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    environment: str = "development"
    deployment_mode: Literal["web", "telegram"] = "web"
    polling_timeout: int = Field(default=25, ge=1, le=50)
    maintenance_interval: int = Field(default=900, ge=60, le=3600)
    polling_max_bots: int = Field(default=20, ge=1, le=100)
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
    trial_days: int = Field(default=3, ge=3, le=3)
    billing_grace_days: int = Field(default=3, ge=0, le=14)
    background_workers: int = Field(default=2, ge=1, le=8)
    interactive_workers: int = Field(default=2, ge=1, le=8)
    payment_webhooks_enabled: bool = False
    telegram_transport: Literal["polling", "webhook"] = "polling"
    port: int = Field(default=8000, ge=1, le=65535)
    storage_path: str = "./storage"
    receipt_storage: Literal["filesystem", "database"] = "filesystem"
    max_upload_bytes: int = 5 * 1024 * 1024
    telegram_test_environment: bool = False
    demo_enabled: bool = False
    worker_lease_seconds: int = 180
    jobs_per_tenant_round: int = 5
    bot_rps: int = 20
    tenant_rps: int = 30
    global_rps: int = 300
    user_rps: int = 1

    @field_validator("trial_days", mode="before")
    @classmethod
    def migrate_legacy_trial_setting(cls, value):
        # Existing single-worker deployments supplied 7. New trials are always
        # three days; an already-started historical trial keeps its stored end.
        return 3 if value in (7, "7") else value

    @property
    def owner_ids(self) -> set[int]:
        return {int(x.strip()) for x in self.platform_owner_ids.split(",") if x.strip()}

    @model_validator(mode="after")
    def production_guard(self):
        if self.environment == "production":
            if (
                self.payment_webhooks_enabled or self.telegram_transport == "webhook"
            ) and not self.public_api_url.startswith("https://"):
                raise ValueError("Webhook ingress requires a public HTTPS URL")
            if (
                self.telegram_transport == "webhook"
                and len(self.master_webhook_secret.get_secret_value()) < 32
            ):
                raise ValueError("Master webhook secret is required")
            if self.demo_enabled or not self.database_url.get_secret_value().startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL and demo disabled")
            if not self.system_database_url:
                raise ValueError("Production requires distinct system database role")
            if self.system_database_url == self.database_url:
                raise ValueError("API and system database credentials must differ")
            if self.deployment_mode == "web":
                if not self.redis_url:
                    raise ValueError("Web production requires Redis")
                if not self.public_api_url.startswith("https://") or not self.mini_app_url.startswith(
                    "https://"
                ):
                    raise ValueError("Production requires HTTPS URLs")
                if len(self.master_webhook_secret.get_secret_value()) < 32:
                    raise ValueError("Master webhook secret is required")
            elif not self.master_bot_username or not self.owner_ids or any(x <= 0 for x in self.owner_ids):
                raise ValueError("Telegram production requires master username and numeric owner IDs")
            if not self.master_bot_token.get_secret_value():
                raise ValueError("Master credentials are required")
            if not json.loads(self.encryption_keys.get_secret_value()):
                raise ValueError("Encryption keyring is required")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
