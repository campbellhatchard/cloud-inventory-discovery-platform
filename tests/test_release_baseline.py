from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_release_is_v090_and_power_shell_toolkit_is_documented() -> None:
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    render_yaml = (ROOT / "render.yaml").read_text(encoding="utf-8")
    sw = (ROOT / "app" / "static" / "sw.js").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert 'app_version: str = "0.9.0"' in config
    assert 'version = "0.9.0"' in pyproject
    assert 'value: "0.9.0"' in render_yaml
    assert "ci-discovery-v0.9.0" in sw
    assert "PowerShell deployment" in readme
    assert (ROOT / "Deploy.ps1").exists()
    assert (ROOT / "scripts" / "Deploy-CloudInventoryDiscovery.ps1").exists()


def test_render_blueprint_keeps_environment_scoped_resource_names() -> None:
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    project = blueprint["projects"][0]
    environment = project["environments"][0]
    database = environment["databases"][0]

    expected = {
        "Staging": {"suffix": "staging", "branch": "staging"},
        "Production": {"suffix": "production", "branch": "main"},
    }
    assert environment["name"] in expected
    contract = expected[environment["name"]]
    suffix = contract["suffix"]

    assert project["name"] == f"cloud-inventory-discovery-{suffix}"
    assert database["databaseName"] == "discovery"
    assert database["name"] == f"cloud-inventory-discovery-{suffix}-db"
    assert all(service["branch"] == contract["branch"] for service in environment["services"])


def test_required_health_and_deployment_files_exist() -> None:
    for relative in [
        "Dockerfile",
        "render.yaml",
        "render.template.yaml",
        "scripts/render-predeploy.sh",
        "scripts/Deploy-CloudInventoryDiscovery.ps1",
        "docs/POWERSHELL_DEPLOYMENT.md",
        "docs/DEPLOYMENT.md",
    ]:
        assert (ROOT / relative).exists(), relative
