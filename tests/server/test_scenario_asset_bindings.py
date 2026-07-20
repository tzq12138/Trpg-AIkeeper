import json

import pytest

from tests.server.conftest import create_room, login, setup_auth_test_data


def _insert_version(test_db, version_id: str, graph: dict, version_number: int = 1):
    test_db.execute(
        "INSERT INTO scenario_versions "
        "(scenario_version_id, scenario_id, version_number, status, knowledge_graph, created_by) "
        "VALUES (%s, 'asset-scenario', %s, 'draft', %s, 'admin')",
        (version_id, version_number, json.dumps(graph, ensure_ascii=False)),
    )


def _graph():
    return {
        "solo_adventure": {
            "root_node_id": "1",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "1",
                    "title": "条目 1",
                    "text": "你在车站等候长途车。",
                    "target_node_ids": ["263"],
                },
                {
                    "node_id": "263",
                    "title": "条目 263",
                    "text": "灰色长途车驶向烬头村。",
                    "target_node_ids": [],
                },
            ],
        },
        "items": [{"item_id": "ticket", "name": "车票", "description": "前往阿卡姆的车票"}],
        "endings": [{"ending_id": "fire", "name": "火焰结局", "description": "熊熊烈火"}],
    }


@pytest.mark.parametrize("filename", ["火.png", "炎.png", "熊熊.png", "风景.png", "旅途.png"])
def test_local_binding_does_not_autobind_generic_image_names_by_substring(filename):
    from src.server.scenario.asset_binding import _binding_targets, _local_suggestion

    suggestion = _local_suggestion(
        {"original_name": filename},
        _binding_targets(_graph()),
    )

    assert suggestion["confidence"] == 0
    assert suggestion["evidence"]["method"] == "unmatched"


@pytest.mark.asyncio
async def test_imported_image_materializes_once_and_generates_versioned_binding_draft(
    test_db, tmp_path
):
    from src.server.scenario.asset_binding import ScenarioAssetBindingService

    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title) VALUES ('asset-scenario', '向火独行')"
    )
    test_db.execute(
        "INSERT INTO source_documents "
        "(source_document_id, scenario_id, source_kind, title, source_filename, mime_type, "
        "source_sha256, storage_path, license_type, status, created_by) "
        "VALUES ('source-image', 'asset-scenario', 'scenario', '向火独行', '长途车.png', "
        "'image/png', 'image-sha', 'asset-scenario/source-image/长途车.png', "
        "'authorized', 'ready', 'admin')"
    )
    _insert_version(test_db, "asset-version-1", _graph())
    source_root = tmp_path / "sources"
    source_path = source_root / "asset-scenario" / "source-image" / "长途车.png"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    service = ScenarioAssetBindingService(
        test_db,
        asset_root=tmp_path / "assets",
    )
    source_rows = [{
        "source_document_id": "source-image",
        "filename": "长途车.png",
        "mime_type": "image/png",
        "relative_path": "asset-scenario/source-image/长途车.png",
    }]

    first_assets = service.materialize_source_images(
        "asset-scenario", source_rows, source_root
    )
    second_assets = service.materialize_source_images(
        "asset-scenario", source_rows, source_root
    )
    bindings = await service.generate_bindings("asset-version-1")

    assert first_assets == second_assets
    assert len(first_assets) == 1
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM scenario_assets WHERE scenario_id = 'asset-scenario'"
    ).fetchone()["count"] == 1
    assert bindings[0]["asset_id"] == first_assets[0]["asset_id"]
    assert bindings[0]["target_type"] == "branch_node"
    assert bindings[0]["target_key"] == "1"
    assert bindings[0]["status"] == "draft"
    assert bindings[0]["confidence"] >= 0.8


@pytest.mark.asyncio
async def test_confirmed_binding_is_version_isolated_and_rejects_unknown_target(
    test_db, tmp_path
):
    from src.server.scenario.asset_binding import AssetBindingError, ScenarioAssetBindingService

    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title) VALUES ('asset-scenario', '向火独行')"
    )
    _insert_version(test_db, "asset-version-1", _graph(), 1)
    _insert_version(test_db, "asset-version-2", _graph(), 2)
    test_db.execute(
        "INSERT INTO scenario_assets "
        "(asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path, visibility) "
        "VALUES ('ticket-image', 'asset-scenario', 'ticket.png', '车票.png', 'image/png', 10, "
        "'data/scenario_assets/asset-scenario/ticket.png', 'host_only')"
    )
    service = ScenarioAssetBindingService(test_db, asset_root=tmp_path)
    draft = (await service.generate_bindings("asset-version-1"))[0]

    with pytest.raises(AssetBindingError, match="binding_target_not_found"):
        service.review_binding(
            draft["binding_id"],
            target_type="branch_node",
            target_key="999",
            status="confirmed",
            reviewed_by="admin",
        )

    confirmed = service.review_binding(
        draft["binding_id"],
        target_type="item",
        target_key="ticket",
        status="confirmed",
        reviewed_by="admin",
    )

    assert confirmed["status"] == "confirmed"
    assert service.confirmed_asset_for_target(
        "asset-version-1", "item", "ticket"
    )["asset_id"] == "ticket-image"
    assert service.confirmed_asset_for_target(
        "asset-version-2", "item", "ticket"
    ) is None


@pytest.mark.asyncio
async def test_multimodal_gateway_binding_wins_over_filename_fallback(test_db, tmp_path):
    from src.server.scenario.asset_binding import ScenarioAssetBindingService

    class Gateway:
        received_assets = None
        received_targets = None

        async def bind_scenario_assets(self, assets, targets):
            self.received_assets = assets
            self.received_targets = targets
            return [{
                "asset_id": "fire-image",
                "target_type": "ending",
                "target_key": "fire",
                "confidence": 0.94,
                "evidence": {"visual": "画面中是吞没建筑的火焰"},
            }]

    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title) VALUES ('asset-scenario', '向火独行')"
    )
    _insert_version(test_db, "asset-version-1", _graph())
    asset_dir = tmp_path / "asset-scenario"
    asset_dir.mkdir()
    (asset_dir / "fire.png").write_bytes(b"\x89PNG\r\n\x1a\nfire")
    test_db.execute(
        "INSERT INTO scenario_assets "
        "(asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path, visibility) "
        "VALUES ('fire-image', 'asset-scenario', 'fire.png', '未命名图片.png', 'image/png', 12, "
        "'data/scenario_assets/asset-scenario/fire.png', 'host_only')"
    )
    gateway = Gateway()
    service = ScenarioAssetBindingService(test_db, asset_root=tmp_path, gateway=gateway)

    binding = (await service.generate_bindings("asset-version-1"))[0]

    assert gateway.received_assets[0]["data_url"].startswith("data:image/png;base64,")
    assert any(target["target_type"] == "ending" for target in gateway.received_targets)
    assert binding["target_type"] == "ending"
    assert binding["target_key"] == "fire"
    assert binding["generated_by"] == "gateway"
    assert binding["evidence"]["visual"] == "画面中是吞没建筑的火焰"


def test_admin_generates_lists_and_confirms_asset_bindings(
    client, test_db, monkeypatch, tmp_path
):
    from src.server.main import app

    setup_auth_test_data(test_db)
    test_db.execute(
        "UPDATE scenarios SET knowledge_graph = %s WHERE scenario_id = 'sc-test'",
        (json.dumps(_graph(), ensure_ascii=False),),
    )
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = 'sv-sc-test'",
        (json.dumps(_graph(), ensure_ascii=False),),
    )
    asset_dir = tmp_path / "sc-test"
    asset_dir.mkdir()
    (asset_dir / "ticket.png").write_bytes(b"\x89PNG\r\n\x1a\nticket")
    test_db.execute(
        "INSERT INTO scenario_assets "
        "(asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path, visibility) "
        "VALUES ('ticket-admin', 'sc-test', 'ticket.png', '车票.png', 'image/png', 14, "
        "'data/scenario_assets/sc-test/ticket.png', 'host_only')"
    )
    test_db.commit()
    app.state.scenario_asset_root = tmp_path
    app.state.gateway = None
    headers = {"Authorization": f"Bearer {login(client, 'admin')}"}

    generated = client.post(
        "/api/admin/scenarios/sc-test/versions/sv-sc-test/asset-bindings/generate",
        headers=headers,
    )

    assert generated.status_code == 200, generated.text
    binding = generated.json()["bindings"][0]
    assert binding["target_type"] == "item"
    assert binding["target_key"] == "ticket"
    assert any(
        target["target_type"] == "branch_node" and target["target_key"] == "1"
        for target in generated.json()["targets"]
    )

    confirmed = client.patch(
        f"/api/admin/scenarios/sc-test/versions/sv-sc-test/asset-bindings/{binding['binding_id']}",
        headers=headers,
        json={"target_type": "item", "target_key": "ticket", "status": "confirmed"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"

    listed = client.get(
        "/api/admin/scenarios/sc-test/versions/sv-sc-test/asset-bindings",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["bindings"][0]["status"] == "confirmed"


def test_player_can_fetch_only_confirmed_asset_for_current_solo_entry(
    client, test_db, tmp_path
):
    from src.server.main import app
    from src.server.scenario.content_projection import ContentProjectionService

    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join").json()
    version = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["scenario_version_id"]
    graph = _graph()
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), version),
    )
    ContentProjectionService(test_db).rebuild(version, graph, requested_by="test")
    asset_dir = tmp_path / "sc-test"
    asset_dir.mkdir()
    image_bytes = b"\x89PNG\r\n\x1a\ncurrent-scene"
    (asset_dir / "opening.png").write_bytes(image_bytes)
    (asset_dir / "draft.png").write_bytes(image_bytes)
    (asset_dir / "host-only.png").write_bytes(image_bytes)
    for asset_id, filename, visibility in (
        ("opening", "opening.png", "party"),
        ("draft", "draft.png", "party"),
        ("host-only", "host-only.png", "host_only"),
    ):
        test_db.execute(
            "INSERT INTO scenario_assets "
            "(asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path, visibility) "
            "VALUES (%s, 'sc-test', %s, %s, 'image/png', %s, %s, %s)",
            (
                asset_id,
                filename,
                filename,
                len(image_bytes),
                f"data/scenario_assets/sc-test/{filename}",
                visibility,
            ),
        )
    test_db.execute(
        "INSERT INTO scenario_asset_bindings "
        "(binding_id, scenario_version_id, asset_id, target_type, target_key, confidence, status) "
        "VALUES ('opening-confirmed', %s, 'opening', 'branch_node', '1', 0.9, 'confirmed'), "
        "('opening-draft', %s, 'draft', 'branch_node', '1', 0.9, 'draft'), "
        "('opening-host-only', %s, 'host-only', 'branch_node', '1', 0.9, 'confirmed')",
        (version, version, version),
    )
    test_db.commit()
    app.state.scenario_asset_root = tmp_path
    headers = {"X-Room-Token": joined["player_token"]}

    confirmed = client.get("/api/player/assets/opening", headers=headers)
    draft = client.get("/api/player/assets/draft", headers=headers)
    host_only = client.get("/api/player/assets/host-only", headers=headers)

    assert confirmed.status_code == 200
    assert confirmed.content == image_bytes
    assert draft.status_code == 404
    assert host_only.status_code == 404
