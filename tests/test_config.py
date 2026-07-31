from __future__ import annotations

import pytest

from app.config import Settings


PRODUCTION_BASE = {
    "environment": "production",
    "deployment_environment": "staging",
    "database_url": "postgresql://user:password@db.example.invalid/discovery",
    "storage_mode": "s3",
    "s3_endpoint": "https://storage.example.invalid",
    "s3_bucket": "discovery-staging",
    "s3_access_key_id": "access-key",
    "s3_secret_access_key": "secret-key",
}


def test_production_web_requires_bootstrap_password() -> None:
    settings = Settings(app_component="web", bootstrap_admin_password=None, **PRODUCTION_BASE)
    with pytest.raises(RuntimeError, match="BOOTSTRAP_ADMIN_PASSWORD"):
        settings.validate_production()


def test_production_worker_does_not_require_bootstrap_password() -> None:
    settings = Settings(app_component="worker", **PRODUCTION_BASE)
    settings.validate_production()


def test_production_rejects_non_postgres_database() -> None:
    settings = Settings(
        environment="production",
        deployment_environment="staging",
        app_component="worker",
        database_url="sqlite:///./discovery.db",
        storage_mode="s3",
        s3_endpoint="https://storage.example.invalid",
        s3_bucket="discovery-staging",
        s3_access_key_id="access-key",
        s3_secret_access_key="secret-key",
    )
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        settings.validate_production()


def test_confidential_ai_requires_zero_data_retention() -> None:
    settings = Settings(
        app_component="worker",
        ai_confidential_content_enabled=True,
        openai_data_control_mode="standard-disabled-for-confidential",
        **PRODUCTION_BASE,
    )
    with pytest.raises(RuntimeError, match="zero_data_retention"):
        settings.validate_production()
