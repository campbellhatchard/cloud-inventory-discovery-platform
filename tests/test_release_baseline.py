from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_password_modal_uses_document_level_event_delegation() -> None:
    app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert "document.addEventListener('submit',handleSubmit);" in app_js
    assert "document.addEventListener('click',handleClick);" in app_js
    assert "const me=await api('/api/auth/me',{},false);" in app_js
    assert "state.me.force_password_change=false" not in app_js


def test_render_predeploy_contract() -> None:
    script = ROOT / "scripts" / "render-predeploy.sh"
    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "python -m alembic upgrade head" in text
    assert "python -m app.seed" in text

    for name in ("render.yaml", "render.template.yaml"):
        blueprint = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
        web = blueprint["projects"][0]["environments"][0]["services"][0]
        assert web["preDeployCommand"] == "/bin/sh scripts/render-predeploy.sh"


def test_release_version_is_consistent() -> None:
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    service_worker = (ROOT / "app" / "static" / "sw.js").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.11"' in config
    assert 'version = "0.8.11"' in pyproject
    assert "ci-discovery-v0.8.11" in service_worker
