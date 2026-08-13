from tests.server.conftest import login, setup_auth_test_data


def test_map_generator_prefers_the_provider_agnostic_gateway_before_legacy_fallback():
    import asyncio

    from src.server.ai.map_generator import MapGenerator

    class Gateway:
        async def generate_map(self, scenes):
            return {
                "nodes": [{"nodeId": "arrival", "name": "码头", "position": {"x": 50, "y": 50}}],
                "edges": [],
            }

    draft = asyncio.run(MapGenerator(api_key="legacy-key", gateway=Gateway()).generate_draft([{"name": "旧场景"}]))

    assert draft["nodes"] == [{
        "node_id": "arrival",
        "name": "码头",
        "description": "",
        "npcs_present": [],
        "clues_available": [],
        "position": {"x": 50, "y": 50},
        "is_start": True,
    }]
    assert draft["regions"][0]["nodeId"] == "arrival"


def test_map_generator_rejects_an_incomplete_gateway_map_and_uses_deterministic_fallback():
    import asyncio

    from src.server.ai.map_generator import MapGenerator

    class Gateway:
        async def generate_map(self, scenes):
            return {"nodes": [{"nodeId": "only", "name": "不完整地图"}], "edges": []}

    draft = asyncio.run(MapGenerator(gateway=Gateway()).generate_draft([
        {"name": "大厅"}, {"name": "图书馆"},
    ]))

    assert [node["node_id"] for node in draft["nodes"]] == ["node_0", "node_1"]
    assert draft["paths"][0]["fromNodeId"] == "node_0"
    assert draft["paths"][0]["toNodeId"] == "node_1"


def test_admin_map_generation_persists_reviewable_region_and_path_drafts(client, test_db, monkeypatch):
    from src.server.ai.map_generator import MapGenerator

    captured = {}

    async def deterministic_draft(self, scenes, base_asset=None):
        captured["scenes"] = scenes
        captured["base_asset"] = base_asset
        return {
            "map_type": "hybrid" if base_asset else "graph",
            "base_asset": base_asset or {},
            "nodes": [
                {"node_id": "node_0", "name": "大厅", "position": {"x": 50, "y": 15}, "is_start": True},
                {"node_id": "node_1", "name": "图书馆", "position": {"x": 50, "y": 85}, "is_start": False},
            ],
            "edges": [{"from_node": "node_0", "to_node": "node_1", "is_one_way": False, "label": ""}],
            "regions": [
                {"regionId": "region-node_0", "nodeId": "node_0", "polygon": [[0.45, 0.1], [0.55, 0.1], [0.55, 0.2], [0.45, 0.2]]},
                {"regionId": "region-node_1", "nodeId": "node_1", "polygon": [[0.45, 0.8], [0.55, 0.8], [0.55, 0.9], [0.45, 0.9]]},
            ],
            "paths": [{"pathId": "path-0", "fromNodeId": "node_0", "toNodeId": "node_1", "isOneWay": False, "label": ""}],
        }

    monkeypatch.setattr(MapGenerator, "generate_draft", deterministic_draft)
    setup_auth_test_data(test_db)
    test_db.execute(
        "INSERT INTO scenario_versions "
        "(scenario_version_id, scenario_id, version_number, knowledge_graph, created_by) "
        "VALUES ('sc-test-v2', 'sc-test', 2, %s, 'admin-1')",
        (
            '{"scenes":['
            '{"sceneId":"station","name":"草稿车站","description":"太阳高悬。"},'
            '{"sceneId":"village","name":"烬头村","description":"村庄地图。"}'
            ']}' ,
        ),
    )
    test_db.execute(
        "INSERT INTO scenario_assets "
        "(asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path, visibility) "
        "VALUES ('map-asset', 'sc-test', 'map-asset.png', '地图.png', 'image/png', 10, "
        "'data/scenario_assets/sc-test/map-asset.png', 'host_only')"
    )
    test_db.commit()

    response = client.post(
        "/api/admin/scenarios/sc-test/map/generate?scenario_version_id=sc-test-v2",
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "draft"
    assert payload["mapType"] == "hybrid"
    assert payload["baseAsset"] == {"assetId": "map-asset"}
    assert captured["scenes"][0]["name"] == "草稿车站"
    assert captured["base_asset"] == {"assetId": "map-asset"}
    assert [region["nodeId"] for region in payload["regions"]] == ["node_0", "node_1"]
    assert len(payload["regions"][0]["polygon"]) == 4
    assert all(
        0 <= coordinate <= 1
        for point in payload["regions"][0]["polygon"]
        for coordinate in point
    )
    assert payload["paths"] == [{
        "pathId": "path-0",
        "fromNodeId": "node_0",
        "toNodeId": "node_1",
        "isOneWay": False,
        "label": "",
    }]

    saved = client.get(
        "/api/admin/scenarios/sc-test/map",
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )
    assert saved.status_code == 200
    assert saved.json()["regions"] == payload["regions"]
    assert saved.json()["paths"] == payload["paths"]


def test_admin_map_generation_times_out_to_local_fallback_without_losing_base_asset(
    client, test_db, monkeypatch
):
    import src.server.router_admin as router_admin
    from src.server.ai.map_generator import MapGenerator

    async def force_timeout(awaitable, timeout):
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(router_admin.asyncio, "wait_for", force_timeout)
    setup_auth_test_data(test_db)
    test_db.execute(
        "UPDATE scenarios SET knowledge_graph = %s WHERE scenario_id = 'sc-test'",
        ('{"scenes":[{"name":"车站"},{"name":"村庄"}]}',),
    )
    test_db.execute(
        "INSERT INTO scenario_assets "
        "(asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path, visibility) "
        "VALUES ('map-fallback', 'sc-test', 'map.png', 'map.png', 'image/png', 10, "
        "'data/scenario_assets/sc-test/map.png', 'host_only')"
    )
    test_db.commit()

    response = client.post(
        "/api/admin/scenarios/sc-test/map/generate",
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["generatedBy"] == "python"
    assert payload["mapType"] == "hybrid"
    assert payload["baseAsset"] == {"assetId": "map-fallback"}
    assert len(payload["nodes"]) == 2


def test_admin_can_preview_a_scenario_map_asset(client, test_db, monkeypatch, tmp_path):
    import src.server.router_admin as router_admin

    setup_auth_test_data(test_db)
    asset_dir = tmp_path / "sc-test"
    asset_dir.mkdir()
    image_bytes = b"\x89PNG\r\n\x1a\nmap-preview"
    (asset_dir / "map-preview.png").write_bytes(image_bytes)
    monkeypatch.setattr(router_admin, "ASSETS_ROOT", tmp_path)
    test_db.execute(
        "INSERT INTO scenario_assets "
        "(asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path, visibility) "
        "VALUES ('map-preview', 'sc-test', 'map-preview.png', '地图.png', 'image/png', %s, "
        "'data/scenario_assets/sc-test/map-preview.png', 'host_only')",
        (len(image_bytes),),
    )
    test_db.commit()

    response = client.get(
        "/api/admin/scenarios/sc-test/assets/map-preview/content",
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == image_bytes


def test_admin_cannot_delete_asset_used_as_confirmed_map_base(client, test_db):
    setup_auth_test_data(test_db)
    test_db.execute(
        "INSERT INTO scenario_assets "
        "(asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path, visibility) "
        "VALUES ('map-in-use', 'sc-test', 'map.png', '地图.png', 'image/png', 10, "
        "'data/scenario_assets/sc-test/map.png', 'host_only')"
    )
    test_db.execute(
        "INSERT INTO scenario_maps "
        "(map_id, scenario_id, generated_by, status, map_type, base_asset, nodes, edges, regions, paths) "
        "VALUES ('map-confirmed', 'sc-test', 'test', 'confirmed', 'image', %s, '[]', '[]', '[]', '[]')",
        ('{"assetId":"map-in-use"}',),
    )
    test_db.commit()

    response = client.delete(
        "/api/admin/scenarios/sc-test/assets/map-in-use",
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )

    assert response.status_code == 409
    assert "引用" in response.json()["detail"]


def test_admin_can_install_a_golden_module_as_a_ready_to_play_scenario(client, test_db):
    setup_auth_test_data(test_db)
    test_db.execute(
        "INSERT INTO rule_sets (rule_set_id, name, slug, system, is_base, license_type, created_by, status) "
        "VALUES ('coc7-base', 'CoC7', 'coc7', 'coc7', TRUE, 'open', 'test', 'published')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions (rule_set_version_id, rule_set_id, version_number, status, runtime_eligible, created_by) "
        "VALUES ('coc7-base-v1', 'coc7-base', 1, 'published', TRUE, 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_version_publication_gates (rule_set_version_id, status) "
        "VALUES ('coc7-base-v1', 'ready')"
    )
    test_db.commit()

    installed = client.post(
        "/api/admin/golden-modules/golden-solo-tide-letter/install",
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )

    assert installed.status_code == 201
    payload = installed.json()
    assert payload["title"] == "潮痕来信"
    assert payload["status"] == "published"
    scenario = test_db.execute(
        "SELECT publish_status, knowledge_graph, scenario_assets, quality_report "
        "FROM scenarios WHERE scenario_id = %s",
        (payload["scenarioId"],),
    ).fetchone()
    assert scenario["publish_status"] == "published"
    assert scenario["knowledge_graph"]["spoiler_boundaries"]["host_ai_only"]
    assert scenario["scenario_assets"]["text_map"]["title"] == "雾港潮汐路线"
    binding = test_db.execute(
        "SELECT rule_set_version_id FROM scenario_rule_bindings WHERE scenario_version_id = %s",
        (payload["scenarioVersionId"],),
    ).fetchone()
    assert binding["rule_set_version_id"] == "coc7-base-v1"
    template_count = test_db.execute(
        "SELECT COUNT(*) AS count FROM character_templates WHERE scenario_id = %s",
        (payload["scenarioId"],),
    ).fetchone()
    assert template_count["count"] == 1
    scenario_map = test_db.execute(
        "SELECT status, nodes, edges FROM scenario_maps WHERE scenario_id = %s",
        (payload["scenarioId"],),
    ).fetchone()
    assert scenario_map["status"] == "confirmed"
    assert scenario_map["edges"] == [
        {"from_node": "tide-archive", "to_node": "old-pier", "is_one_way": False, "label": "石阶小路"},
        {"from_node": "old-pier", "to_node": "signal-tower", "is_one_way": False, "label": "潮湿栈道"},
    ]
    library = client.get("/api/library")
    assert payload["scenarioId"] in [item["scenario_id"] for item in library.json()["items"]]


def test_golden_module_install_uses_a_qualified_official_base_over_retired_legacy_version(client, test_db):
    setup_auth_test_data(test_db)
    test_db.execute(
        "INSERT INTO rule_sets (rule_set_id, name, slug, system, is_base, license_type, created_by, status) VALUES "
        "('official-base', 'Official CoC7', 'official-coc7-core', 'coc7', TRUE, 'authorized', 'test', 'published'), "
        "('retired-base', 'Retired CoC7', 'coc7', 'coc7', TRUE, 'authorized', 'test', 'published')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions (rule_set_version_id, rule_set_id, version_number, status, "
        "runtime_eligible, metadata, created_by) VALUES "
        "('official-base-v1', 'official-base', 1, 'published', TRUE, '{}', 'test'), "
        "('retired-base-v99', 'retired-base', 99, 'published', FALSE, "
        "'{\"local_test_only\": true}', 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_version_publication_gates (rule_set_version_id, status) VALUES "
        "('official-base-v1', 'ready'), ('retired-base-v99', 'ready')"
    )
    test_db.commit()

    installed = client.post(
        "/api/admin/golden-modules/golden-solo-tide-letter/install",
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )

    assert installed.status_code == 201
    binding = test_db.execute(
        "SELECT rule_set_version_id FROM scenario_rule_bindings WHERE scenario_version_id = %s",
        (installed.json()["scenarioVersionId"],),
    ).fetchone()
    assert binding == {"rule_set_version_id": "official-base-v1"}


def test_golden_module_install_builds_a_ready_cited_runtime_package(client, test_db):
    setup_auth_test_data(test_db)
    test_db.execute(
        "INSERT INTO rule_sets (rule_set_id, name, slug, system, is_base, license_type, created_by, status) "
        "VALUES ('coc7-base', 'CoC7', 'coc7', 'coc7', TRUE, 'open', 'test', 'published')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions (rule_set_version_id, rule_set_id, version_number, status, runtime_eligible, created_by) "
        "VALUES ('coc7-base-v1', 'coc7-base', 1, 'published', TRUE, 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_version_publication_gates (rule_set_version_id, status) "
        "VALUES ('coc7-base-v1', 'ready')"
    )
    test_db.commit()

    installed = client.post(
        "/api/admin/golden-modules/golden-team-glass-rain/install",
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )

    assert installed.status_code == 201
    payload = installed.json()
    assert payload["runtimePackage"]["gate_status"] == "ready"
    runtime_package = payload["runtimePackage"]["runtime_package"]
    assert runtime_package["runtime_policy"] == {
        "runtime_version": "v2",
        "session_mode": "ai_only",
        "state_scope": "room_run",
        "archive_on_end": True,
        "fresh_state_on_new_room": True,
        "in_game_time": {
            "day_key": "glass-rain-night-1",
            "expected_duration_hours": 3,
        },
        "safety": {
            "anonymous_pause": True,
            "resume_authority": "triggering_player",
            "table_steward_actions": ["extend", "end_session"],
            "safe_abort_ending_id": "glass-safe-abort",
        },
        "ai_failure_policy": {
            "pre_commit": "deterministic_fallback",
            "post_commit": "preserve_state_template_narration",
        },
    }
    assert runtime_package["rule_triggers"][0]["condition"] == {
        "$action": "move",
        "targetNodeId": "cistern",
    }
    assert runtime_package["rule_triggers"][0]["mechanics"][0]["type"] == "sanity_check"
    assert runtime_package["rule_triggers"][0]["mechanics"][0]["blocking"] is False
    assert runtime_package["ending_conditions"]
    assert {
        ending["type"] for ending in runtime_package["ending_conditions"]
    } >= {"victory", "mixed", "safe_abort"}
    assert all(
        ending["citation"].get("source_part_id")
        and ending["completion_conditions"]
        for ending in runtime_package["ending_conditions"]
    )
    assert any(
        edge["from_scene_id"] == "glass-gate"
        and edge["to_scene_id"] == "orchid-hall"
        and edge["citation"].get("source_part_id")
        for edge in runtime_package["semantic_progression_rules"]["edges"]
    )
    content_items = test_db.execute(
        "SELECT item_type, citation FROM content_items WHERE scenario_version_id = %s",
        (payload["scenarioVersionId"],),
    ).fetchall()
    assert {item["item_type"] for item in content_items} >= {
        "scene", "npc", "clue", "ending", "truth",
    }
    assert all(item["citation"].get("source_part_id") for item in content_items)


def test_second_golden_playthrough_module_installs_with_a_ready_runtime_package(client, test_db):
    setup_auth_test_data(test_db)
    test_db.execute(
        "INSERT INTO rule_sets (rule_set_id, name, slug, system, is_base, license_type, created_by, status) "
        "VALUES ('coc7-base', 'CoC7', 'coc7', 'coc7', TRUE, 'open', 'test', 'published')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions (rule_set_version_id, rule_set_id, version_number, status, runtime_eligible, created_by) "
        "VALUES ('coc7-base-v1', 'coc7-base', 1, 'published', TRUE, 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_version_publication_gates (rule_set_version_id, status) "
        "VALUES ('coc7-base-v1', 'ready')"
    )
    test_db.commit()

    installed = client.post(
        "/api/admin/golden-modules/golden-sandbox-lost-property/install",
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )

    assert installed.status_code == 201
    runtime_package = installed.json()["runtimePackage"]
    assert runtime_package["gate_status"] == "ready"
    assert any(
        edge["from_scene_id"] == "lost-property-counter"
        and edge["to_scene_id"] == "harbor-post"
        for edge in runtime_package["runtime_package"]["semantic_progression_rules"]["edges"]
    )
