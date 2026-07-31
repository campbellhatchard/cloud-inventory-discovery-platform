from __future__ import annotations


def test_prospect_isolation(admin_session):
    client, admin = admin_session
    h = {"X-CSRF-Token": admin["csrf_token"]}
    created = client.post(
        "/api/admin/users",
        json={
            "username": "isolated-user",
            "email": "isolated@example.com",
            "display_name": "Isolated User",
            "password": "Temporary-Password!2026",
            "roles": ["CONTRIBUTOR"],
        },
        headers=h,
    )
    assert created.status_code in {200, 409}
    prospect = client.post("/api/prospects", json={"name": "Private Prospect"}, headers=h)
    assert prospect.status_code == 200
    private_id = prospect.json()["id"]

    with client.__class__(client.app) as other:
        login = other.post(
            "/api/auth/login",
            json={"username": "isolated-user", "password": "Temporary-Password!2026"},
        )
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        changed = other.post(
            "/api/auth/change-password",
            json={
                "current_password": "Temporary-Password!2026",
                "new_password": "Replacement-Password!2026",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert changed.status_code == 200
        denied = other.get(f"/api/prospects/{private_id}")
        assert denied.status_code == 403
        visible = other.get("/api/prospects")
        assert visible.status_code == 200
        assert private_id not in {p["id"] for p in visible.json()}
