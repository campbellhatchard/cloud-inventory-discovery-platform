from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def test_guided_onboarding_creates_linked_records_and_routes_to_reports(admin_session) -> None:
    client, me = admin_session
    response = client.post(
        "/api/prospects/onboard",
        json={
            "prospect": {"name": "Guided Prospect", "industry": "Distribution", "opportunity": "Improve field capture"},
            "site": {"name": "London Operations", "address": "London, UK", "timezone": "Europe/London"},
            "engagement": {"name": "Initial discovery", "survey_date": "2026-08-15", "objectives": "Document current operations"},
        },
        headers=headers(me),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["site_id"]
    assert result["engagement_id"]
    assert result["next_tab"] == "reports"

    prospect = client.get(f"/api/prospects/{result['id']}")
    assert prospect.status_code == 200
    payload = prospect.json()
    assert payload["sites"][0]["timezone"] == "Europe/London"
    assert payload["engagements"][0]["site_id"] == result["site_id"]


def test_guided_onboarding_skip_routes(admin_session) -> None:
    client, me = admin_session
    prospect_only = client.post(
        "/api/prospects/onboard",
        json={"prospect": {"name": "Prospect Only"}, "site": None, "engagement": None},
        headers=headers(me),
    )
    assert prospect_only.status_code == 200, prospect_only.text
    assert prospect_only.json()["next_tab"] == "sites"

    with_site = client.post(
        "/api/prospects/onboard",
        json={"prospect": {"name": "Prospect and Site"}, "site": {"name": "Main Site", "timezone": "Australia/Melbourne"}, "engagement": None},
        headers=headers(me),
    )
    assert with_site.status_code == 200, with_site.text
    assert with_site.json()["next_tab"] == "engagements"


def test_frontend_timezone_and_logo_contract() -> None:
    app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    sw_js = (ROOT / "app" / "static" / "sw.js").read_text(encoding="utf-8")
    documents = (ROOT / "app" / "documents.py").read_text(encoding="utf-8")

    assert "id=\"prospect-onboarding-form\"" in app_js
    assert "Intl.DateTimeFormat().resolvedOptions().timeZone" in app_js
    assert "Intl.supportedValuesOf('timeZone')" in app_js
    assert "Europe/London" in app_js
    assert "Europe/Guernsey" in app_js
    assert "Australia/Melbourne" in app_js
    assert "/static/cloud-inventory-logo-for-dark-background-v0.4.1.png" in app_js
    assert "/static/cloud-inventory-logo-for-light-background-v0.4.1.png" in app_js
    assert "ci-discovery-v0.8.9" in sw_js
    assert "cloud-inventory-logo-for-light-background-v0.4.1.png" in documents
    assert (ROOT / "app" / "static" / "cloud-inventory-logo-for-light-background-v0.4.1.png").exists()
    assert (ROOT / "app" / "static" / "cloud-inventory-logo-for-dark-background-v0.4.1.png").exists()
