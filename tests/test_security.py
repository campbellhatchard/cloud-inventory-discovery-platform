from __future__ import annotations

from app.ai_service import evaluate_policy
from app.config import Settings
from app.storage import build_storage_key, safe_filename


def test_storage_keys_are_prospect_scoped_and_sanitized():
    name = safe_filename("../../bad name<script>.jpg")
    assert "/" not in name
    assert "<" not in name
    key = build_storage_key("prospect-1", "evidence", "object-1", "../../bad name.jpg")
    assert key.startswith("prospects/prospect-1/evidence/object-1/")
    assert ".." not in key


def test_confidential_ai_requires_zdr():
    settings = Settings(
        environment="test",
        ai_enabled=True,
        ai_confidential_content_enabled=True,
        openai_api_key="test-key",
        openai_data_control_mode="standard-disabled-for-confidential",
    )
    decision = evaluate_policy(settings, contains_prospect_confidential_content=True)
    assert not decision.allowed
    assert decision.mode == "zdr-required"


def test_confidential_ai_allowed_only_after_explicit_zdr_gate():
    settings = Settings(
        environment="test",
        ai_enabled=True,
        ai_confidential_content_enabled=True,
        openai_api_key="test-key",
        openai_data_control_mode="zero_data_retention",
    )
    assert evaluate_policy(settings, contains_prospect_confidential_content=True).allowed
