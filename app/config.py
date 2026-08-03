from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    deployment_environment: Literal["local", "staging", "production"] = "local"
    app_component: Literal["web", "worker"] = "web"
    app_name: str = "Cloud Inventory Site Discovery"
    app_version: str = "0.6.0"
    app_base_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./discovery.db"
    session_cookie_name: str = "ci_discovery_session"
    session_ttl_hours: int = 12
    bootstrap_admin_username: str = "Admin"
    bootstrap_admin_password: str | None = None
    bootstrap_admin_email: str = "admin@example.invalid"
    default_retention_days: int = 1095
    merge_source_recovery_days: int = 30

    storage_mode: Literal["local", "s3"] = "local"
    local_storage_root: Path = Path("./local-storage")
    s3_endpoint: str | None = None
    s3_region: str = "auto"
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    signed_url_ttl_seconds: int = 300
    max_upload_bytes: int = 52_428_800

    openai_api_key: str | None = None
    openai_project_id: str | None = None
    openai_model: str = "gpt-5-mini"
    ai_enabled: bool = False
    ai_confidential_content_enabled: bool = False
    openai_data_control_mode: Literal["zero_data_retention", "standard-disabled-for-confidential"] = (
        "standard-disabled-for-confidential"
    )

    libreoffice_path: str = "/usr/bin/libreoffice"
    document_work_dir: Path = Path("/tmp/ci-discovery-documents")
    job_poll_seconds: float = 2.0
    maintenance_interval_seconds: int = 3600
    retention_warning_days: int = 30
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def normalize_render_postgres_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    def validate_production(self) -> None:
        if self.environment != "production":
            return
        if not self.database_url.startswith("postgresql+psycopg://"):
            raise RuntimeError("Production requires a PostgreSQL DATABASE_URL.")
        if self.app_component == "web" and not self.bootstrap_admin_password:
            raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD must be configured as a Render secret for the web service.")
        if self.storage_mode != "s3":
            raise RuntimeError("Production requires STORAGE_MODE=s3 because service filesystems are not authoritative storage.")
        missing = [
            name
            for name, value in {
                "S3_ENDPOINT": self.s3_endpoint,
                "S3_BUCKET": self.s3_bucket,
                "S3_ACCESS_KEY_ID": self.s3_access_key_id,
                "S3_SECRET_ACCESS_KEY": self.s3_secret_access_key,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing S3 settings: {', '.join(missing)}")
        if self.ai_enabled and not self.openai_api_key:
            raise RuntimeError("AI_ENABLED=true requires OPENAI_API_KEY.")
        if self.ai_confidential_content_enabled and self.openai_data_control_mode != "zero_data_retention":
            raise RuntimeError("Confidential AI processing requires OPENAI_DATA_CONTROL_MODE=zero_data_retention.")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_production()
    return settings
