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

    async def deterministic_draft(self, scenes, base_asset=None):
        return {
            "map_type": "graph",
            "base_asset": {},
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
        "UPDATE scenarios SET knowledge_graph = %s WHERE scenario_id = 'sc-test'",
        (
            '{"scenes":['
            '{"sceneId":"hall","name":"大厅","description":"大厅里有一座落地钟。"},'
            '{"sceneId":"library","name":"图书馆","description":"书架间有潮湿的纸张。"}'
            ']}' ,
        ),
    )
    test_db.commit()

    response = client.post(
        "/api/admin/scenarios/sc-test/map/generate",
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "draft"
    assert payload["mapType"] == "graph"
    assert payload["baseAsset"] == {}
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


def test_admin_can_install_a_golden_module_as_a_ready_to_play_scenario(client, test_db):
    setup_auth_test_data(test_db)
    test_db.execute(
        "INSERT INTO rule_sets (rule_set_id, name, slug, system, license_type, created_by, status) "
        "VALUES ('coc7-base', 'CoC7', 'coc7', 'coc7', 'open', 'test', 'published')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions (rule_set_version_id, rule_set_id, version_number, status, created_by) "
        "VALUES ('coc7-base-v1', 'coc7-base', 1, 'published', 'test')"
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
