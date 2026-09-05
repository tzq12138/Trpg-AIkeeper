import json
from pathlib import Path

from tests.server.conftest import login, setup_auth_test_data


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "golden_modules"
    / "03-investigation-sandbox-lost-property"
    / "module.json"
)


def _module() -> dict:
    return json.loads(MODULE_PATH.read_text(encoding="utf-8"))


def _publish_coc7_rule_version(test_db) -> None:
    test_db.execute(
        "INSERT INTO rule_sets "
        "(rule_set_id, name, slug, system, is_base, license_type, created_by, status) "
        "VALUES ('coc7-base', 'CoC7', 'coc7', 'coc7', TRUE, 'open', 'test', 'published')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions "
        "(rule_set_version_id, rule_set_id, version_number, status, runtime_eligible, created_by) "
        "VALUES ('coc7-base-v1', 'coc7-base', 1, 'published', TRUE, 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_version_publication_gates (rule_set_version_id, status) "
        "VALUES ('coc7-base-v1', 'ready')"
    )
    test_db.commit()


def test_lost_property_declares_a_complete_v2_ai_only_runtime_contract():
    """Removing the v2 contract declaration or a required runtime field must fail."""
    from src.server.scenario.module_compiler import _runtime_contract_issues

    module = _module()
    graph = module["knowledge_graph"]

    assert module["manifest"]["runtime_version"] == "v2"
    assert graph["runtime_policy"]["runtime_contract_version"] == "v1"
    assert graph["runtime_policy"]["session_mode"] == "ai_only"
    assert _runtime_contract_issues(graph) == []


def test_lost_property_installs_as_a_ready_v2_ai_only_runtime_package(client, test_db):
    """The real golden-module installer must preserve the authored v2 contract."""
    setup_auth_test_data(test_db)
    _publish_coc7_rule_version(test_db)

    installed = client.post(
        "/api/admin/golden-modules/golden-sandbox-lost-property/install",
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )

    assert installed.status_code == 201, installed.text
    runtime_package = installed.json()["runtimePackage"]
    runtime = runtime_package["runtime_package"]
    assert runtime_package["gate_status"] == "ready"
    assert runtime["runtime_contract_version"] == "v1"
    assert runtime["runtime_policy"]["session_mode"] == "ai_only"
    assert runtime["risk_contract"]["safe_abort_rule"] == "lost-safe-abort"
    assert any(
        ending["ending_id"] == "lost-safe-abort" and ending["type"] == "safe_abort"
        for ending in runtime["ending_conditions"]
    )


def test_golden_module_upgrade_publishes_a_new_version_without_overwriting_v1(client, test_db):
    """A newer golden-module source must become v2, while v1 stays addressable."""
    setup_auth_test_data(test_db)
    _publish_coc7_rule_version(test_db)
    headers = {"Authorization": f"Bearer {login(client, 'admin')}"}

    initial = client.post(
        "/api/admin/golden-modules/golden-sandbox-lost-property/install",
        headers=headers,
    )
    assert initial.status_code == 201, initial.text
    scenario_id = initial.json()["scenarioId"]
    v1_id = initial.json()["scenarioVersionId"]
    test_db.execute(
        "UPDATE source_documents SET source_sha256 = 'stale-golden-module' "
        "WHERE scenario_id = %s AND source_kind = 'golden_module'",
        (scenario_id,),
    )
    test_db.commit()

    upgraded = client.post(
        "/api/admin/golden-modules/golden-sandbox-lost-property/upgrade",
        headers=headers,
    )

    assert upgraded.status_code == 201, upgraded.text
    payload = upgraded.json()
    assert payload["scenarioId"] == scenario_id
    assert payload["scenarioVersionId"] != v1_id
    assert payload["runtimePackage"]["gate_status"] == "ready"
    assert payload["runtimePackage"]["runtime_package"]["runtime_contract_version"] == "v1"
    versions = client.get(f"/api/scenarios/{scenario_id}/versions", headers=headers)
    assert versions.status_code == 200, versions.text
    assert any(version["scenario_version_id"] == v1_id for version in versions.json())
    assert next(
        version for version in versions.json()
        if version["scenario_version_id"] == payload["scenarioVersionId"]
    )["is_active"] is True
