from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_logo_assets_match_background_context() -> None:
    app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    documents = (ROOT / "app" / "documents.py").read_text(encoding="utf-8")
    manifest = (ROOT / "app" / "static" / "manifest.json").read_text(encoding="utf-8")
    index_html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    service_worker = (ROOT / "app" / "static" / "sw.js").read_text(encoding="utf-8")
    light_name = "cloud-inventory-logo-for-light-background-v0.4.1.png"
    dark_name = "cloud-inventory-logo-for-dark-background-v0.4.1.png"
    assert f'class="logo-on-dark" src="/static/{dark_name}"' in app_js
    assert f'class="login-logo logo-on-light" src="/static/{light_name}"' in app_js
    assert light_name in documents
    assert light_name in manifest
    assert light_name in index_html
    assert light_name in service_worker
    assert dark_name in service_worker
    assert "ci-discovery-v0.8.6" in service_worker
    assert (ROOT / "app" / "static" / light_name).is_file()
    assert (ROOT / "app" / "static" / dark_name).is_file()
