import base64
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.models import MechanicCompileResult
from src.server.scenario.solo_runtime import SoloAdventureRuntime
from src.server.engine.engine import Engine
from src.server.main import app
from src.server.router_auth import _hash_password


class FakeGateway:
    package = None

    async def structure_content_package(self, package):
        self.package = package
        image_parts = [part for part in package.parts if part.kind == "image"]
        return {
            "title": "钟楼疑云",
            "synopsis": "调查员受邀调查钟楼中的失踪事件。",
            "scenes": [
                {"name": "钟楼大厅", "description": "尘封的大厅", "order": 1},
                {"name": "地下室", "description": "隐藏的祭坛", "order": 2},
            ],
            "npcs": [{
                "npc_id": "caretaker",
                "name": "守钟人",
                "public_description": "沉默的老人",
                "description": "知道地下室入口",
                "personality": "谨慎",
                "motivation": "阻止仪式",
                "is_hidden": False,
            }],
            "clues": [{
                "name": "黑色钥匙", "description": "可打开地下室", "location": "钟楼大厅"
            }],
            "truth": {"summary": "地下室正在举行召唤仪式"},
            "endings": [{
                "ending_id": "stop-ritual",
                "name": "阻止仪式",
                "description": "摧毁祭坛",
                "type": "victory",
                "completion_conditions": {"room_status": "active"},
                "citation": {"source_ref": "page:1"},
            }],
            "spoiler_boundaries": [{"id": "truth", "level": "keeper"}],
            "key_skills": ["侦查", "聆听", "神秘学"],
            "rule_citations": [{"source_ref": "coc7-srd#checks"}],
            "source_part_texts": [
                {
                    "source_ref": part.source_ref,
                    "text": "图像中可见钟楼平面与通往地下室的楼梯。",
                }
                for part in image_parts
            ],
        }


class FakeRag:
    scenario_calls = []
    npc_calls = []

    def __init__(self):
        self.scenario_calls = []
        self.npc_calls = []
        self.content_calls = []
        self.embedding = type(
            "FakeEmbeddingMetadata",
            (),
            {"model_name": "fake-embedding-v2", "dimension": 1536},
        )()

    def index_scenario_version(self, *args, **kwargs):
        self.scenario_calls.append((args, kwargs))
        return len(args[2])

    def index_npc_graph(self, *args, **kwargs):
        self.npc_calls.append((args, kwargs))
        return 1

    def index_content_projection(self, *args, **kwargs):
        self.content_calls.append((args, kwargs))
        return len(args[2])


class UnavailableMultimodalGateway:
    async def structure_content_package(self, package):
        raise RuntimeError("multimodal_provider_unavailable")


class NoTranscriptGateway(FakeGateway):
    async def structure_content_package(self, package):
        result = await super().structure_content_package(package)
        result.pop("source_part_texts", None)
        return result


def test_runtime_contract_repair_only_runs_for_missing_executable_graph():
    from src.server.scenario.import_service import _needs_runtime_contract_repair

    assert _needs_runtime_contract_repair({"branches": [], "endings": []}) is True
    assert _needs_runtime_contract_repair({
        "branches": [{
            "from_scene_id": "study",
            "to_scene_id": "harbor",
            "citation": {"source_ref": "page:1"},
        }],
        "endings": [{
            "ending_id": "escape",
            "citation": {"source_ref": "page:2"},
            "completion_conditions": {"entered_scenes": ["harbor"]},
        }],
    }) is False


class CamelCaseBranchGateway(FakeGateway):
    async def structure_content_package(self, package):
        result = await super().structure_content_package(package)
        result["scenes"] = [
            {
                "sceneId": "tower-hall",
                "name": "钟楼大厅",
                "description": "尘封的大厅",
                "order": 1,
            },
            {
                "sceneId": "cellar",
                "name": "地下室",
                "description": "隐藏的祭坛",
                "order": 2,
            },
        ]
        result["branches"] = [{
            "branchId": "tower-hall-to-cellar",
            "fromSceneId": "tower-hall",
            "toSceneId": "cellar",
            "conditions": [{"kind": "clue", "id": "black-key"}],
            "citation": {"source_ref": "page:1", "page_number": 1},
        }]
        return result


@pytest.fixture
def import_client(test_db, tmp_path):
    client = TestClient(app)
    app.state.db = test_db
    app.state.engine = Engine(test_db)
    app.state.gateway = FakeGateway()
    app.state.rag = FakeRag()
    app.state.scenario_storage_root = tmp_path / "scenarios"
    app.state.scenario_asset_root = tmp_path / "scenario-assets"
    for account_id, username, role in [
        ("import-admin", "importadmin", "admin"),
        ("import-host", "importhost", "host"),
        ("import-player", "importplayer", "player"),
    ]:
        test_db.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES (?, ?, ?, ?, ?)",
            (account_id, username, _hash_password("test123"), username, role),
        )
    return client


def test_import_normalizes_camel_case_branches_into_projected_scene_edges(import_client, test_db):
    app.state.gateway = CamelCaseBranchGateway()
    admin_token = _login(import_client, "importadmin")

    response = import_client.post(
        "/api/scenarios/import",
        files={
            "files": (
                "module.docx",
                _minimal_docx("钟楼大厅通向地下室。"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"title": "分支导入测试", "license_type": "authorized"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    scenario_version_id = response.json()["scenario_version_id"]
    graph = test_db.execute(
        "SELECT knowledge_graph FROM scenario_versions WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()["knowledge_graph"]
    assert graph["scenes"][0]["scene_id"] == "tower-hall"
    assert graph["branches"] == [{
        "branch_id": "tower-hall-to-cellar",
        "from_scene_id": "tower-hall",
        "to_scene_id": "cellar",
        "conditions": [{"kind": "clue", "id": "black-key"}],
        "citation": {"source_ref": "page:1", "page_number": 1},
    }]
    edge = test_db.execute(
        "SELECT relation_type, conditions, citation FROM content_item_edges "
        "WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()
    assert edge["relation_type"] == "transitions_to"
    assert edge["conditions"] == [{"kind": "clue", "id": "black-key"}]
    assert edge["citation"] == {"source_ref": "page:1", "page_number": 1}


def test_multimodal_import_review_publish_and_room_snapshot(import_client, test_db):
    admin_token = _login(import_client, "importadmin")
    original_module = _minimal_docx("钟楼大厅。黑色钥匙藏在祭坛下。")
    response = import_client.post(
        "/api/scenarios/import",
        files=[
            (
                "files",
                (
                    "module.docx",
                        original_module,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            ),
            ("files", ("map.png", _pixel_png(), "image/png")),
        ],
        data={
            "title": "钟楼疑云",
            "license_type": "authorized",
            "license_ref": "internal-license-42",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "draft_ready"
    assert payload["source_document_count"] == 2
    assert payload["requires_multimodal"] is True
    scenario_id = payload["scenario_id"]
    scenario_version_id = payload["scenario_version_id"]
    job_id = payload["job_ids"][0]

    imported_asset = test_db.execute(
        "SELECT asset_id, original_name, source_document_id FROM scenario_assets "
        "WHERE scenario_id = %s",
        (scenario_id,),
    ).fetchone()
    assert imported_asset["original_name"] == "map.png"
    assert imported_asset["source_document_id"]
    binding = test_db.execute(
        "SELECT binding_id, target_type, target_key, status FROM scenario_asset_bindings "
        "WHERE scenario_version_id = %s AND asset_id = %s",
        (scenario_version_id, imported_asset["asset_id"]),
    ).fetchone()
    assert {
        "target_type": binding["target_type"],
        "target_key": binding["target_key"],
        "status": binding["status"],
    } == {"target_type": "map", "target_key": "map", "status": "draft"}

    scenario = test_db.execute(
        "SELECT import_status, publish_status, published_version_id FROM scenarios "
        "WHERE scenario_id = ?",
        (scenario_id,),
    ).fetchone()
    version = test_db.execute(
        "SELECT status, prep_package, quality_report FROM scenario_versions "
        "WHERE scenario_version_id = ?",
        (scenario_version_id,),
    ).fetchone()
    assert scenario["import_status"] == "draft_review"
    assert scenario["publish_status"] == "draft"
    assert scenario["published_version_id"] is None
    assert version["status"] == "draft"
    assert len(app.state.rag.scenario_calls) == 0
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM document_chunks WHERE scenario_version_id = ?",
        (scenario_version_id,),
    ).fetchone()["count"] == 0
    projected_types = {
        row["item_type"]
        for row in test_db.execute(
            "SELECT item_type FROM content_items WHERE scenario_version_id = %s",
            (scenario_version_id,),
        ).fetchall()
    }
    assert {"scene", "npc", "clue", "truth", "ending"} <= projected_types
    projection = test_db.execute(
        "SELECT status FROM content_projection_runs "
        "WHERE scenario_version_id = %s AND projection_kind = 'canonical_content'",
        (scenario_version_id,),
    ).fetchone()
    assert projection["status"] == "completed"

    status = import_client.get(
        f"/api/scenarios/import-jobs/{job_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert status.status_code == 200
    assert status.json()["status"] == "complete"
    assert status.json()["progress"] == 100

    host_token = _login(import_client, "importhost")
    host_preview = import_client.get(
        f"/api/scenarios/{scenario_id}/versions/{scenario_version_id}/prep",
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert host_preview.status_code == 200, host_preview.text
    assert "prep_package" not in host_preview.json()
    assert "truth" not in host_preview.json()
    assert host_preview.json()["summary"]
    assert host_preview.json()["citations"]

    admin_preview = import_client.get(
        f"/api/scenarios/{scenario_id}/versions/{scenario_version_id}/prep",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_preview.status_code == 200
    assert admin_preview.json()["prep_package"]["npcs"][0]["motivation"] == "阻止仪式"

    confirmed_binding = import_client.patch(
        f"/api/admin/scenarios/{scenario_id}/versions/{scenario_version_id}"
        f"/asset-bindings/{binding['binding_id']}",
        json={"target_type": "map", "target_key": "map", "status": "confirmed"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert confirmed_binding.status_code == 200, confirmed_binding.text
    test_db.execute(
        "INSERT INTO character_templates "
        "(template_id, scenario_id, name, occupation, attributes, skills, backstory) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            f"{scenario_id}-template",
            scenario_id,
            "钟楼调查员",
            "研究者",
            json.dumps({"pow": 50}),
            json.dumps({"侦查": 50}),
            json.dumps({}),
        ),
    )
    test_db.commit()
    runtime_package = _make_runtime_package_ready(
        import_client, scenario_id, scenario_version_id, admin_token
    )
    assert runtime_package["gate_status"] == "ready", runtime_package["quality_exceptions"]

    published = import_client.post(
        f"/api/scenarios/{scenario_id}/versions/{scenario_version_id}/publish",
        json={"confirm": True, "review_notes": "房主已检查线索与规则依据"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert len(app.state.rag.scenario_calls) == 1
    assert app.state.rag.scenario_calls[0][0][1] == scenario_version_id
    indexed_parts = app.state.rag.scenario_calls[0][0][2]
    indexed_images = [part for part in indexed_parts if part["part_kind"] == "image"]
    assert indexed_images
    assert indexed_images[0]["text"] == "图像中可见钟楼平面与通往地下室的楼梯。"
    assert indexed_images[0]["anchor"]["transcript_status"] == "provider"
    assert app.state.rag.npc_calls[0][1]["scenario_version_id"] == scenario_version_id
    assert app.state.rag.content_calls[0][0][1] == scenario_version_id
    assert {item["item_type"] for item in app.state.rag.content_calls[0][0][2]} >= {
        "scene", "npc", "clue", "truth", "ending"
    }
    rebuild = test_db.execute(
        "SELECT embedding_model, embedding_dimensions FROM rag_rebuild_records "
        "WHERE scenario_version_id = ?",
        (scenario_version_id,),
    ).fetchone()
    assert rebuild["embedding_model"] == "fake-embedding-v2"
    assert rebuild["embedding_dimensions"] == 1536

    room_response = import_client.post(
        "/api/rooms",
        json={"scenario_id": scenario_id},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert room_response.status_code == 200, room_response.text
    room = test_db.execute(
        "SELECT scenario_id, scenario_version_id FROM rooms WHERE room_id = ?",
        (room_response.json()["room_id"],),
    ).fetchone()
    assert room["scenario_id"] == scenario_id
    assert room["scenario_version_id"] == scenario_version_id

    version_two_import = import_client.post(
        "/api/scenarios/import",
        files={
            "files": (
                "module-v2.docx",
                _minimal_docx("第二版：钟楼地下室新增了一条秘密通道。"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={
            "scenario_id": scenario_id,
            "title": "钟楼疑云 第二版",
            "license_type": "authorized",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert version_two_import.status_code == 200, version_two_import.text
    scenario_version_two = version_two_import.json()["scenario_version_id"]
    assert scenario_version_two != scenario_version_id
    runtime_package_two = _make_runtime_package_ready(
        import_client, scenario_id, scenario_version_two, admin_token
    )
    assert runtime_package_two["gate_status"] == "ready"

    publish_two = import_client.post(
        f"/api/scenarios/{scenario_id}/versions/{scenario_version_two}/publish",
        json={"confirm": True, "review_notes": "确认第二版"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert publish_two.status_code == 200, publish_two.text
    current = test_db.execute(
        "SELECT published_version_id FROM scenarios WHERE scenario_id = ?",
        (scenario_id,),
    ).fetchone()
    old_room = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = ?",
        (room_response.json()["room_id"],),
    ).fetchone()
    assert current["published_version_id"] == scenario_version_two
    assert old_room["scenario_version_id"] == scenario_version_id

    rollback = import_client.post(
        f"/api/scenarios/{scenario_id}/versions/{scenario_version_id}/activate",
        json={"confirm": True},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["active_version_id"] == scenario_version_id

    new_room_response = import_client.post(
        "/api/rooms",
        json={"scenario_id": scenario_id},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    new_room = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = ?",
        (new_room_response.json()["room_id"],),
    ).fetchone()
    assert new_room["scenario_version_id"] == scenario_version_id

    duplicate = import_client.post(
        "/api/scenarios/import",
        files={
            "files": (
                "module.docx",
                    original_module,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"license_type": "authorized"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "already_imported"
    assert duplicate.json()["scenario_id"] == scenario_id


def test_admin_rebuilds_draft_from_existing_sources_without_mutating_old_version(
    import_client, test_db
):
    admin_token = _login(import_client, "importadmin")
    imported = import_client.post(
        "/api/scenarios/import",
        files={
            "files": (
                "module.docx",
                _minimal_docx("钟楼大厅。黑色钥匙藏在祭坛下。"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"title": "钟楼重编译", "license_type": "authorized"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert imported.status_code == 200, imported.text
    original = imported.json()
    scenario_id = original["scenario_id"]
    original_version_id = original["scenario_version_id"]
    original_graph = test_db.execute(
        "SELECT knowledge_graph FROM scenario_versions WHERE scenario_version_id = %s",
        (original_version_id,),
    ).fetchone()["knowledge_graph"]
    original_job = test_db.execute(
        "SELECT job_id, diagnostics FROM import_jobs WHERE scenario_id = %s",
        (scenario_id,),
    ).fetchone()

    rebuilt = import_client.post(
        f"/api/scenarios/{scenario_id}/versions/{original_version_id}/rebuild-from-sources",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert rebuilt.status_code == 200, rebuilt.text
    payload = rebuilt.json()
    assert payload["status"] == "draft_ready"
    assert payload["scenario_version_id"] != original_version_id
    assert payload["version_number"] == 2
    assert test_db.execute(
        "SELECT knowledge_graph FROM scenario_versions WHERE scenario_version_id = %s",
        (original_version_id,),
    ).fetchone()["knowledge_graph"] == original_graph
    assert test_db.execute(
        "SELECT diagnostics FROM import_jobs WHERE job_id = %s",
        (original_job["job_id"],),
    ).fetchone()["diagnostics"] == original_job["diagnostics"]
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM scenario_version_sources WHERE scenario_version_id = %s",
        (payload["scenario_version_id"],),
    ).fetchone()["count"] == 1


def test_malformed_import_persists_failed_job(import_client, test_db):
    token = _login(import_client, "importadmin")
    response = import_client.post(
        "/api/scenarios/import",
        files={
            "files": (
                "broken.docx",
                b"not a docx zip",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"license_type": "authorized"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422
    job_id = response.json()["detail"]["job_ids"][0]
    row = test_db.execute(
        "SELECT status, error_message FROM import_jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    assert row["status"] == "failed"
    assert row["error_message"]


def test_scenario_version_list_is_ordered_and_role_projected(import_client, test_db):
    admin_token = _login(import_client, "importadmin")
    imported = import_client.post(
        "/api/scenarios/import",
        files={
            "files": (
                "module.docx",
                _minimal_docx("钟楼大厅。黑色钥匙藏在祭坛下。"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"title": "钟楼疑云", "license_type": "authorized"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert imported.status_code == 200, imported.text
    scenario_id = imported.json()["scenario_id"]
    scenario_version_id = imported.json()["scenario_version_id"]

    player_token = _login(import_client, "importplayer")
    denied = import_client.get(
        f"/api/scenarios/{scenario_id}/versions",
        headers={"Authorization": f"Bearer {player_token}"},
    )
    assert denied.status_code == 403

    host_token = _login(import_client, "importhost")
    host_result = import_client.get(
        f"/api/scenarios/{scenario_id}/versions",
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert host_result.status_code == 200, host_result.text
    assert host_result.json()[0]["scenario_version_id"] == scenario_version_id
    assert "quality_report" not in host_result.json()[0]
    assert "review_notes" not in host_result.json()[0]

    admin_result = import_client.get(
        f"/api/scenarios/{scenario_id}/versions",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_result.status_code == 200, admin_result.text
    assert admin_result.json()[0]["scenario_version_id"] == scenario_version_id
    assert admin_result.json()[0]["quality_report"]["level"]
    assert admin_result.json()[0]["is_active"] is False


def test_awaiting_provider_import_can_retry_after_multimodal_api_switch(
    import_client, test_db
):
    admin_token = _login(import_client, "importadmin")
    app.state.gateway = UnavailableMultimodalGateway()
    pending = import_client.post(
        "/api/scenarios/import",
        files={"files": ("scan.png", _pixel_png(), "image/png")},
        data={"title": "待识别扫描剧本", "license_type": "authorized"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] == "awaiting_provider"
    job_id = pending.json()["job_ids"][0]
    scenario_id = pending.json()["scenario_id"]

    scenario_list = import_client.get(
        "/api/admin/scenarios",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert scenario_list.status_code == 200, scenario_list.text
    listed = next(
        item for item in scenario_list.json() if item["scenario_id"] == scenario_id
    )
    assert listed["latest_import_job_id"] == job_id
    assert listed["latest_import_job_status"] == "awaiting_provider"
    assert "error_message" not in listed

    host_token = _login(import_client, "importhost")
    denied = import_client.post(
        f"/api/scenarios/import-jobs/{job_id}/retry",
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert denied.status_code == 403

    app.state.gateway = FakeGateway()
    retried = import_client.post(
        f"/api/scenarios/import-jobs/{job_id}/retry",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "draft_ready"
    assert retried.json()["scenario_id"] == scenario_id
    assert retried.json()["scenario_version_id"]
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM source_documents WHERE scenario_id = ?",
        (scenario_id,),
    ).fetchone()["count"] == 1
    scenario = test_db.execute(
        "SELECT import_status, publish_status FROM scenarios WHERE scenario_id = ?",
        (scenario_id,),
    ).fetchone()
    assert scenario["import_status"] == "draft_review"
    assert scenario["publish_status"] == "draft"


def test_stale_structuring_import_is_listed_as_retryable(import_client, test_db):
    admin_token = _login(import_client, "importadmin")
    app.state.gateway = UnavailableMultimodalGateway()
    pending = import_client.post(
        "/api/scenarios/import",
        files={"files": ("scan.png", _pixel_png(), "image/png")},
        data={"title": "中断的扫描剧本", "license_type": "authorized"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    job_id = pending.json()["job_ids"][0]
    scenario_id = pending.json()["scenario_id"]
    test_db.execute(
        "UPDATE import_jobs SET status = 'structuring', "
        "updated_at = '2020-01-01 00:00:00' WHERE job_id = ?",
        (job_id,),
    )
    test_db.execute(
        "UPDATE scenarios SET import_status = 'parsing' WHERE scenario_id = ?",
        (scenario_id,),
    )

    response = import_client.get(
        "/api/admin/scenarios",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    listed = next(item for item in response.json() if item["scenario_id"] == scenario_id)
    assert listed["latest_import_job_id"] == job_id
    assert listed["latest_import_job_status"] == "structuring"
    assert listed["latest_import_job_retryable"] is True

    duplicate = import_client.post(
        "/api/scenarios/import",
        files={"files": ("scan.png", _pixel_png(), "image/png")},
        data={"title": "重复上传中断剧本", "license_type": "authorized"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["status"] == "already_imported"
    assert duplicate.json()["job_id"] == job_id
    assert duplicate.json()["retryable"] is True


def test_stale_structuring_import_can_retry_after_worker_interrupt(
    import_client, test_db
):
    admin_token = _login(import_client, "importadmin")
    app.state.gateway = UnavailableMultimodalGateway()
    pending = import_client.post(
        "/api/scenarios/import",
        files={"files": ("scan.png", _pixel_png(), "image/png")},
        data={"title": "中断后恢复", "license_type": "authorized"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    job_id = pending.json()["job_ids"][0]
    scenario_id = pending.json()["scenario_id"]
    test_db.execute(
        "UPDATE import_jobs SET status = 'structuring', "
        "updated_at = '2020-01-01 00:00:00' WHERE job_id = ?",
        (job_id,),
    )
    test_db.execute(
        "UPDATE scenarios SET import_status = 'parsing' WHERE scenario_id = ?",
        (scenario_id,),
    )
    app.state.gateway = FakeGateway()

    retried = import_client.post(
        f"/api/scenarios/import-jobs/{job_id}/retry",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "draft_ready"
    assert retried.json()["scenario_id"] == scenario_id
    assert retried.json()["scenario_version_id"]
    scenario = test_db.execute(
        "SELECT import_status FROM scenarios WHERE scenario_id = ?",
        (scenario_id,),
    ).fetchone()
    assert scenario["import_status"] == "draft_review"


def test_stale_structuring_retry_replaces_outdated_source_parts(
    import_client, test_db
):
    admin_token = _login(import_client, "importadmin")
    imported = import_client.post(
        "/api/scenarios/import",
        files={
            "files": (
                "solo.docx",
                _minimal_docx("1# 正确开场。转到 2。\n2# 正确结局。"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"title": "重试重新解析", "license_type": "authorized"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    scenario_id = imported.json()["scenario_id"]
    job_id = imported.json()["job_ids"][0]
    source_document = test_db.execute(
        "SELECT source_document_id FROM source_documents WHERE scenario_id = ?",
        (scenario_id,),
    ).fetchone()
    test_db.execute(
        "UPDATE source_parts SET text_content = '1# 错误串栏正文。转到 2。' "
        "WHERE source_document_id = ?",
        (source_document["source_document_id"],),
    )
    test_db.execute(
        "UPDATE import_jobs SET status = 'structuring', "
        "updated_at = '2020-01-01 00:00:00' WHERE job_id = ?",
        (job_id,),
    )
    test_db.execute(
        "UPDATE scenarios SET import_status = 'parsing' WHERE scenario_id = ?",
        (scenario_id,),
    )

    retried = import_client.post(
        f"/api/scenarios/import-jobs/{job_id}/retry",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert retried.status_code == 200, retried.text
    version = test_db.execute(
        "SELECT knowledge_graph FROM scenario_versions WHERE scenario_version_id = ?",
        (retried.json()["scenario_version_id"],),
    ).fetchone()
    assert version["knowledge_graph"]["solo_adventure"]["nodes"][0]["text"].startswith(
        "正确开场"
    )
    source_parts = test_db.execute(
        "SELECT text_content FROM source_parts WHERE source_document_id = ?",
        (source_document["source_document_id"],),
    ).fetchall()
    assert len(source_parts) == 1
    assert source_parts[0]["text_content"].startswith("1# 正确开场")


def test_multimodal_import_derives_indexable_text_when_provider_omits_transcript(
    import_client, test_db
):
    admin_token = _login(import_client, "importadmin")
    app.state.gateway = NoTranscriptGateway()

    imported = import_client.post(
        "/api/scenarios/import",
        files={"files": ("map.png", _pixel_png(), "image/png")},
        data={"title": "无独立转写剧本", "license_type": "authorized"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert imported.status_code == 200, imported.text
    source_part = test_db.execute(
        "SELECT sp.text_content, sp.anchor FROM source_parts sp "
        "JOIN source_documents sd ON sd.source_document_id = sp.source_document_id "
        "WHERE sd.scenario_id = ? AND sp.part_kind = 'image'",
        (imported.json()["scenario_id"],),
    ).fetchone()
    assert source_part["text_content"]
    assert source_part["anchor"]["transcript_status"] == "derived_worldbook"


def test_source_image_materialization_failure_keeps_draft_but_blocks_runtime_package(
    import_client, test_db, monkeypatch
):
    from src.server.scenario.asset_binding import ScenarioAssetBindingService

    def fail_materialize(self, *_args, **_kwargs):
        raise RuntimeError("simulated_asset_failure")

    monkeypatch.setattr(
        ScenarioAssetBindingService,
        "materialize_source_images",
        fail_materialize,
    )
    admin_token = _login(import_client, "importadmin")

    imported = import_client.post(
        "/api/scenarios/import",
        files={"files": ("map.png", _pixel_png(), "image/png")},
        data={"title": "素材失败仍生成草稿", "license_type": "authorized"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert imported.status_code == 200, imported.text
    payload = imported.json()
    assert payload["status"] == "draft_ready"
    assert payload["runtime_package"]["gate_status"] == "blocked"
    assert any(
        issue["code"] == "asset_binding_generation_failed"
        and issue["waivable"] is False
        for issue in payload["runtime_package"]["quality_exceptions"]
    )
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM scenario_assets WHERE scenario_id = %s",
        (payload["scenario_id"],),
    ).fetchone()["count"] == 0


def test_import_projects_numbered_solo_adventure_nodes(import_client, test_db):
    admin_token = _login(import_client, "importadmin")
    imported = import_client.post(
        "/api/scenarios/import",
        files={
            "files": (
                "solo.docx",
                _minimal_docx("1# 你抵达车站。转到 2。\n2# 车门在你身后关上。"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"title": "编号单人冒险", "license_type": "authorized"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert imported.status_code == 200, imported.text
    scenario_version_id = imported.json()["scenario_version_id"]
    version = test_db.execute(
        "SELECT knowledge_graph FROM scenario_versions WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()
    solo = version["knowledge_graph"]["solo_adventure"]
    assert solo["integrity"]["is_valid"] is True
    assert solo["nodes"][0]["target_node_ids"] == ["2"]
    assert solo["nodes"][0]["citation"]["source_part_id"]
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM content_items "
        "WHERE scenario_version_id = %s AND item_type = 'branch_node'",
        (scenario_version_id,),
    ).fetchone()["count"] == 2


def test_invalid_numbered_solo_adventure_cannot_be_published(import_client, test_db):
    admin_token = _login(import_client, "importadmin")
    imported = import_client.post(
        "/api/scenarios/import",
        files={
            "files": (
                "invalid-solo.docx",
                _minimal_docx("1# 第一段。转到 3。\n1# 重复条目。\n2# 另一段。"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"title": "无效编号冒险", "license_type": "authorized"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert imported.status_code == 200, imported.text
    quality = test_db.execute(
        "SELECT quality_report FROM scenario_versions WHERE scenario_version_id = %s",
        (imported.json()["scenario_version_id"],),
    ).fetchone()["quality_report"]
    assert quality["level"] == "blocked"
    assert any(issue["category"] == "solo_adventure" for issue in quality["issues"])
    response = import_client.post(
        f"/api/scenarios/{imported.json()['scenario_id']}/versions/"
        f"{imported.json()['scenario_version_id']}/publish",
        json={"confirm": True, "review_notes": "尝试绕过无效分支"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "invalid_solo_adventure"


def test_blocked_quality_report_cannot_be_published_even_by_admin(import_client, test_db):
    admin_token = _login(import_client, "importadmin")
    scenario_id = "quality-blocked"
    version_id = "quality-blocked-v1"
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, raw_text, import_status, publish_status) "
        "VALUES (%s, %s, %s, %s, %s)",
        (scenario_id, "质量阻塞剧本", "测试内容", "draft_ready", "draft"),
    )
    test_db.execute(
        "INSERT INTO scenario_versions (scenario_version_id, scenario_id, version_number, status, quality_report, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (
            version_id,
            scenario_id,
            1,
            "draft_review",
            json.dumps({"level": "blocked", "issues": [{"message": "缺少可绑定的关键素材"}]}),
            "import-admin",
        ),
    )
    test_db.commit()

    response = import_client.post(
        f"/api/scenarios/{scenario_id}/versions/{version_id}/publish",
        json={"confirm": True, "review_notes": "管理员尝试发布"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "quality_blocked"


@pytest.mark.asyncio
async def test_alone_against_the_flames_pdf_imports_publishes_and_binds_room(
    import_client, test_db
):
    admin_token = _login(import_client, "importadmin")
    source = (
        Path(__file__).resolve().parents[2]
        / "data" / "test_assets" / "最小测试模块" / "向火独行.pdf"
    )
    imported = import_client.post(
        "/api/scenarios/import",
        files={"files": (source.name, source.read_bytes(), "application/pdf")},
        data={"title": "向火独行原版验收", "license_type": "authorized"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert imported.status_code == 200, imported.text
    payload = imported.json()
    version = test_db.execute(
        "SELECT knowledge_graph FROM scenario_versions WHERE scenario_version_id = %s",
        (payload["scenario_version_id"],),
    ).fetchone()
    integrity = version["knowledge_graph"]["solo_adventure"]["integrity"]
    assert integrity["node_count"] == 270
    assert integrity["edge_count"] == 410
    assert integrity["is_valid"] is True
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM content_items "
        "WHERE scenario_version_id = %s AND item_type = 'branch_node'",
        (payload["scenario_version_id"],),
    ).fetchone()["count"] == 270
    template = test_db.execute(
        "SELECT name, occupation, attributes, skills, backstory "
        "FROM character_templates WHERE scenario_id = %s",
        (payload["scenario_id"],),
    ).fetchone()
    assert template["name"] == "独行调查员"
    assert template["occupation"] == "旅行者"
    assert template["attributes"]["pow"] == 50
    assert template["skills"]["侦查"] == 50
    assert [item["name"] for item in template["backstory"]["initial_inventory"]] == [
        "行李箱",
        "笔记本和钢笔",
    ]

    host_token = _login(import_client, "importhost")
    runtime_package = _make_runtime_package_ready(
        import_client, payload["scenario_id"], payload["scenario_version_id"], admin_token
    )
    assert runtime_package["gate_status"] == "ready"
    published = import_client.post(
        f"/api/scenarios/{payload['scenario_id']}/versions/{payload['scenario_version_id']}/publish",
        json={"confirm": True, "review_notes": "原版编号图验收通过"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert published.status_code == 200, published.text
    room = import_client.post(
        "/api/rooms",
        json={"scenario_id": payload["scenario_id"]},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert room.status_code == 200, room.text
    bound = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room.json()["room_id"],),
    ).fetchone()
    assert bound["scenario_version_id"] == payload["scenario_version_id"]

    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('yhdx-player', %s, '调查员', 'yhdx-player-token', %s)
        """,
        (room.json()["room_id"], json.dumps({"skills": {}})),
    )
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, intent_type, declared_intent,
            params, status, draft_id, idempotency_key
        ) VALUES ('yhdx-first-move', %s, 'yhdx-player', 'move', '我转到条目 263', %s,
                  'queued', 'yhdx-draft', 'yhdx-idempotency')
        """,
            (
                room.json()["room_id"],
                json.dumps({
                    "fromNodeId": "1",
                    "targetNodeId": "263",
                    "director_plan": {
                        "context_version": 0,
                        "preconditions": [],
                        "permissions": [],
                        "state_patch": [],
                        "state_patch_authority": "advisory_only",
                    },
                }),
            ),
        )

    class AutoSuccessCompiler:
        async def compile(self, *_args, **_kwargs):
            return MechanicCompileResult(triggeredMechanic="auto_success")

    class Dispatcher:
        async def emit(self, *_args, **_kwargs):
            return None

    result = await ResolutionPipeline(
        test_db, compiler=AutoSuccessCompiler(), dispatcher=Dispatcher()
    ).resolve_action("yhdx-first-move")
    assert result["status"] == "completed"
    assert SoloAdventureRuntime(test_db).current(room.json()["room_id"])["node_id"] == "263"


def _login(client, username):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "test123"},
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _make_runtime_package_ready(client, scenario_id, scenario_version_id, token):
    bindings = client.get(
        f"/api/admin/scenarios/{scenario_id}/versions/{scenario_version_id}/asset-bindings",
        headers={"Authorization": f"Bearer {token}"},
    )
    if bindings.status_code == 200:
        for binding in bindings.json()["bindings"]:
            if binding["status"] != "confirmed":
                confirmed = client.patch(
                    f"/api/admin/scenarios/{scenario_id}/versions/{scenario_version_id}"
                    f"/asset-bindings/{binding['binding_id']}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "target_type": binding["target_type"],
                        "target_key": binding["target_key"],
                        "status": "confirmed",
                    },
                )
                assert confirmed.status_code == 200, confirmed.text
    recompiled = client.post(
        f"/api/scenarios/{scenario_id}/versions/{scenario_version_id}/runtime-package/recompile",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert recompiled.status_code == 200, recompiled.text
    payload = recompiled.json()
    for issue in list(payload["quality_exceptions"]):
        if issue["waivable"]:
            confirmed = client.post(
                f"/api/scenarios/{scenario_id}/versions/{scenario_version_id}"
                "/runtime-package/exceptions/confirm",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "runtime_package_version_id": payload["runtime_package_version_id"],
                    "exception_key": issue["exception_key"],
                },
            )
            assert confirmed.status_code == 200, confirmed.text
            payload = confirmed.json()
    return payload


def _minimal_docx(text):
    document_xml = f"""<?xml version='1.0' encoding='UTF-8'?>
<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
  <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
</w:document>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _pixel_png():
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO8L5m0AAAAASUVORK5CYII="
    )
