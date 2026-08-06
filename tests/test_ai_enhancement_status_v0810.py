from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_ai_status_three_state_contract_is_rendered_beneath_button():
    js = (_root() / "app/static/app.js").read_text(encoding="utf-8")
    assert "function aiEnhancementReviewStatus(sectionId)" in js
    assert "label:'Not Run'" in js
    assert "label:'Not Reviewed'" in js
    assert "label:'Accepted'" in js
    assert 'data-ai-enhance-status="${section.id}"' in js
    assert "Status: ${esc(aiStatus.label)}" in js
    assert "ai-enhance-control" in js


def test_latest_observation_enhancement_drives_status():
    js = (_root() / "app/static/app.js").read_text(encoding="utf-8")
    assert "item.purpose === 'OBSERVATION_ENHANCEMENT'" in js
    assert "String(right.created_at || '').localeCompare(String(left.created_at || ''))" in js
    assert "suggestions[0].review_state === 'APPROVED'" in js


def test_live_ai_result_updates_status_without_page_navigation():
    js = (_root() / "app/static/app.js").read_text(encoding="utf-8")
    assert "function syncAiEnhancementStatus(sectionId, suggestion)" in js
    assert "syncAiEnhancementStatus(section.id, job.suggestion)" in js
    assert "target.textContent = `Status: ${status.label}`" in js


def test_status_is_compact_secondary_text():
    css = (_root() / "app/static/styles.css").read_text(encoding="utf-8")
    assert ".ai-enhance-control" in css
    assert ".ai-enhance-status" in css
    assert "font-size:10.5px" in css


def test_release_version_is_v0810_without_new_migration():
    root = _root()
    config = (root / "app/config.py").read_text(encoding="utf-8")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    sw = (root / "app/static/sw.js").read_text(encoding="utf-8")
    assert 'app_version: str = "0.8.10"' in config
    assert 'version = "0.8.10"' in pyproject
    assert "ci-discovery-v0.8.10" in sw
    migrations = list((root / "alembic/versions").glob("*.py"))
    assert any("n94k7f3i1g54" in p.name for p in migrations)
    assert not any("v0810" in p.name.lower() or "ai_enhancement_status" in p.name.lower() for p in migrations)
