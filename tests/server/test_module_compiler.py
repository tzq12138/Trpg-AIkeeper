import json

import pytest

from tests.server.conftest import login, setup_auth_test_data


def _insert_compiler_fixture(test_db, *, graph=None):
    graph = graph or _graph_with_citations()
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title) VALUES ('module-scenario', 'Module Scenario')"
    )
    test_db.execute(
        "INSERT INTO scenario_versions "
        "(scenario_version_id, scenario_id, version_number, status, knowledge_graph, prep_package, created_by) "
        "VALUES ('module-version-1', 'module-scenario', 1, 'draft', %s, %s, 'admin')",
        (
            json.dumps(graph, ensure_ascii=False),
            json.dumps({"summary": "Host summary", "citations": [_citation("part-scene")]}, ensure_ascii=False),
        ),
    )
    for item_type, key, title, citation in (
        ("scene", "station", "Station", _citation("part-scene")),
        ("npc", "driver", "Driver", _citation("part-npc")),
        ("clue", "ticket", "Ticket", _citation("part-clue")),
        ("branch_node", "1", "Entry 1", _citation("part-node-1")),
        ("branch_node", "2", "Entry 2", _citation("part-node-2")),
    ):
        test_db.execute(
            "INSERT INTO content_items "
            "(content_item_id, scenario_version_id, item_type, logical_key, title, visibility, payload, citation, checksum) "
            "VALUES (%s, 'module-version-1', %s, %s, %s, 'host_only', %s, %s, %s)",
            (
                f"item-{item_type}-{key}",
                item_type,
                key,
                title,
                json.dumps({"name": title, "description": f"{title} text"}, ensure_ascii=False),
                json.dumps(citation, ensure_ascii=False),
                f"checksum-{item_type}-{key}",
            ),
        )
    test_db.execute(
        "INSERT INTO content_item_edges "
        "(content_item_edge_id, scenario_version_id, from_content_item_id, to_content_item_id, "
        "relation_type, conditions, citation) "
        "VALUES ('edge-1-2', 'module-version-1', 'item-branch_node-1', 'item-branch_node-2', "
        "'transitions_to', '[]', %s)",
        (json.dumps(_citation("part-edge"), ensure_ascii=False),),
    )
    test_db.execute(
        "INSERT INTO scenario_assets "
        "(asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path, visibility) "
        "VALUES ('asset-map', 'module-scenario', 'map.png', 'map.png', 'image/png', 10, "
        "'data/scenario_assets/module-scenario/map.png', 'host_only')"
    )
    test_db.execute(
        "INSERT INTO scenario_asset_bindings "
        "(binding_id, scenario_version_id, asset_id, target_type, target_key, confidence, status) "
        "VALUES ('binding-map', 'module-version-1', 'asset-map', 'map', 'map', 0.99, 'draft')"
    )
    test_db.execute(
        "INSERT INTO character_templates "
        "(template_id, scenario_id, name, occupation, attributes, skills, backstory) "
        "VALUES ('module-template', 'module-scenario', 'Ada', 'Investigator', %s, %s, %s)",
        (
            json.dumps({"hp": 10, "san": 60}),
            json.dumps({"Spot Hidden": 60}),
            json.dumps({"inventory": ["Notebook"]}),
        ),
    )
    test_db.commit()


def _graph_with_citations():
    return {
        "synopsis": "A train station mystery.",
        "scenes": [{"scene_id": "station", "name": "Station", "citation": _citation("part-scene")}],
        "npcs": [{"npc_id": "driver", "name": "Driver", "citation": _citation("part-npc")}],
        "items": [{"item_id": "ticket", "name": "Ticket", "citation": _citation("part-item")}],
        "clues": [{"clue_id": "ticket", "name": "Ticket", "citation": _citation("part-clue")}],
        "endings": [{"ending_id": "safe", "name": "Safe", "citation": _citation("part-ending")}],
        "rule_triggers": [{"trigger": "spot_hidden", "citation": _citation("part-rule")}],
        "style_pack": {"tone": "investigative", "citation": _citation("part-style")},
        "solo_adventure": {
            "root_node_id": "1",
            "integrity": {"is_valid": True, "node_count": 2, "edge_count": 1},
            "nodes": [
                {
                    "node_id": "1",
                    "title": "Entry 1",
                    "text": "Go to 2.",
                    "target_node_ids": ["2"],
                    "citation": _citation("part-node-1"),
                },
                {
                    "node_id": "2",
                    "title": "Entry 2",
                    "text": "End.",
                    "target_node_ids": [],
                    "citation": _citation("part-node-2"),
                },
            ],
        },
    }


def _citation(source_part_id):
    return {"source_part_id": source_part_id, "source_ref": f"module#{source_part_id}"}


def test_runtime_package_blocks_draft_asset_then_ready_after_confirmed_binding(test_db):
    from src.server.scenario.module_compiler import ModuleCompiler

    _insert_compiler_fixture(test_db)
    compiler = ModuleCompiler(test_db)

    blocked = compiler.compile("module-version-1", requested_by="admin")

    assert blocked["gate_status"] == "blocked"
    assert any(
        issue["code"] == "asset_binding_not_confirmed" and issue["blocking"] is True
        for issue in blocked["quality_exceptions"]
    )
    assert set(blocked["runtime_package"].keys()) >= {
        "world_book",
        "semantic_scenes",
        "npc_states",
        "character_and_items",
        "clue_dependencies",
        "rule_triggers",
        "semantic_map",
        "ending_conditions",
        "style_pack",
        "story_evidence_nodes",
        "semantic_progression_rules",
        "citations",
    }

    test_db.execute(
        "UPDATE scenario_asset_bindings SET status = 'confirmed', reviewed_by = 'admin' "
        "WHERE binding_id = 'binding-map'"
    )
    test_db.commit()

    ready = compiler.compile("module-version-1", requested_by="admin")

    assert ready["gate_status"] == "ready"
    assert ready["runtime_package"]["character_and_items"]["templates"][0]["name"] == "Ada"
    assert ready["runtime_package_version_id"] != blocked["runtime_package_version_id"]
    assert ready["package_version_number"] == blocked["package_version_number"] + 1


def test_runtime_package_blocks_when_scenario_has_no_character_template(test_db):
    from src.server.scenario.module_compiler import ModuleCompiler

    _insert_compiler_fixture(test_db)
    test_db.execute("DELETE FROM character_templates WHERE scenario_id = 'module-scenario'")
    test_db.execute(
        "UPDATE scenario_asset_bindings SET status = 'confirmed' WHERE binding_id = 'binding-map'"
    )
    test_db.commit()

    package = ModuleCompiler(test_db).compile("module-version-1", requested_by="admin")

    assert package["gate_status"] == "blocked"
    assert any(
        issue["code"] == "missing_character_template"
        and issue["blocking"] is True
        and issue["waivable"] is False
        for issue in package["quality_exceptions"]
    )


def test_missing_citation_can_be_confirmed_but_invalid_solo_cannot(test_db):
    from src.server.scenario.module_compiler import ModuleCompiler, ModuleCompilerError

    graph = _graph_with_citations()
    graph["scenes"][0].pop("citation")
    graph["solo_adventure"]["integrity"] = {
        "is_valid": False,
        "missing_target_node_ids": ["404"],
        "duplicate_node_ids": [],
    }
    _insert_compiler_fixture(test_db, graph=graph)
    test_db.execute(
        "UPDATE content_items SET citation = '{}' "
        "WHERE scenario_version_id = 'module-version-1' AND item_type = 'scene'"
    )
    test_db.execute(
        "UPDATE scenario_asset_bindings SET status = 'confirmed' WHERE binding_id = 'binding-map'"
    )
    test_db.commit()
    compiler = ModuleCompiler(test_db)

    package = compiler.compile("module-version-1", requested_by="admin")

    missing_citation = next(
        issue for issue in package["quality_exceptions"] if issue["code"] == "missing_citation"
    )
    invalid_solo = next(
        issue for issue in package["quality_exceptions"] if issue["code"] == "invalid_solo_integrity"
    )
    assert missing_citation["waivable"] is True
    assert invalid_solo["waivable"] is False

    with pytest.raises(ModuleCompilerError, match="quality_exception_not_waivable"):
        compiler.confirm_quality_exception(
            package["runtime_package_version_id"],
            invalid_solo["exception_key"],
            confirmed_by="admin",
        )

    compiler.confirm_quality_exception(
        package["runtime_package_version_id"],
        missing_citation["exception_key"],
        confirmed_by="admin",
    )

    preview = compiler.preview(package["runtime_package_version_id"])
    assert preview["gate_status"] == "blocked"
    assert any(
        issue["code"] == "missing_citation" and issue["confirmed"] is True
        for issue in preview["quality_exceptions"]
    )


def test_confirming_waived_exception_updates_persisted_gate_status(test_db):
    from src.server.scenario.module_compiler import ModuleCompiler

    graph = _graph_with_citations()
    graph["scenes"][0].pop("citation")
    _insert_compiler_fixture(test_db, graph=graph)
    test_db.execute(
        "UPDATE content_items SET citation = '{}' "
        "WHERE scenario_version_id = 'module-version-1' AND item_type = 'scene'"
    )
    test_db.execute("UPDATE scenario_asset_bindings SET status = 'confirmed'")
    test_db.commit()
    compiler = ModuleCompiler(test_db)
    package = compiler.compile("module-version-1", requested_by="admin")
    issue = next(
        item for item in package["quality_exceptions"] if item["code"] == "missing_citation"
    )

    confirmed = compiler.confirm_quality_exception(
        package["runtime_package_version_id"],
        issue["exception_key"],
        confirmed_by="admin",
    )

    persisted = test_db.execute(
        "SELECT gate_status FROM runtime_package_versions WHERE runtime_package_version_id = %s",
        (package["runtime_package_version_id"],),
    ).fetchone()
    assert confirmed["gate_status"] == "ready"
    assert persisted["gate_status"] == "ready"


def test_compiler_backfills_missing_item_citation_from_matching_source_part(test_db):
    from src.server.scenario.module_compiler import ModuleCompiler

    graph = _graph_with_citations()
    graph["scenes"][0].pop("citation")
    _insert_compiler_fixture(test_db, graph=graph)
    test_db.execute(
        "UPDATE content_items SET citation = '{}' "
        "WHERE scenario_version_id = 'module-version-1' AND item_type = 'scene'"
    )
    test_db.execute("UPDATE scenario_asset_bindings SET status = 'confirmed'")
    test_db.execute(
        "INSERT INTO source_documents "
        "(source_document_id, scenario_id, source_kind, title, source_filename, mime_type, "
        "source_sha256, storage_path, license_type, status, created_by) "
        "VALUES ('source-module', 'module-scenario', 'scenario', 'Module', 'module.pdf', "
        "'application/pdf', 'source-sha', 'module.pdf', 'authorized', 'ready', 'admin')"
    )
    test_db.execute(
        "INSERT INTO source_parts "
        "(source_part_id, source_document_id, ordinal, part_kind, page_number, text_content, "
        "mime_type, anchor, checksum) VALUES "
        "('matched-scene-part', 'source-module', 1, 'text', 7, "
        "'The Station is silent. Station text describes the empty platform.', "
        "'text/plain', %s, 'part-sha')",
        (json.dumps({"source_ref": "page:7"}),),
    )
    test_db.execute(
        "INSERT INTO scenario_version_sources (scenario_version_id, source_document_id, ordinal) "
        "VALUES ('module-version-1', 'source-module', 1)"
    )
    test_db.commit()

    package = ModuleCompiler(test_db).compile("module-version-1", requested_by="admin")

    assert package["gate_status"] == "ready"
    scene = package["runtime_package"]["semantic_scenes"][0]
    assert scene["citation"]["source_part_id"] == "matched-scene-part"
    assert scene["citation"]["page_number"] == 7
    assert scene["citation"]["evidence_method"] == "deterministic_text_match"


def test_compiler_matches_chinese_evidence_across_particles(test_db):
    from src.server.scenario.module_compiler import _evidence_match_score

    score = _evidence_match_score(
        ["废弃教堂", "坍圮的教堂被用作马棚，有马蹄印和马粪"],
        "这座废弃的教堂曾经被用作马棚，在角落能找到蹄印和干燥的马粪",
    )

    assert score >= 20


def test_invalid_regular_branch_skipped_by_projection_still_blocks_runtime_package(test_db):
    from src.server.scenario.module_compiler import ModuleCompiler

    graph = _graph_with_citations()
    graph["branches"] = [{
        "branch_id": "bad-branch",
        "from_scene_id": "missing-scene",
        "to_scene_id": "station",
        "citation": _citation("part-branch"),
    }]
    _insert_compiler_fixture(test_db, graph=graph)
    test_db.execute("UPDATE scenario_asset_bindings SET status = 'confirmed'")
    test_db.execute(
        "INSERT INTO content_projection_runs "
        "(projection_run_id, scenario_version_id, projection_kind, status, input_checksum, diagnostics, requested_by) "
        "VALUES ('projection-with-diagnostics', 'module-version-1', 'canonical_content', "
        "'completed', 'checksum', %s, 'test')",
        (json.dumps({"warnings": ["branch:bad-branch:missing_scene_target"]}),),
    )
    test_db.commit()

    package = ModuleCompiler(test_db).compile("module-version-1", requested_by="admin")

    issue = next(
        item for item in package["quality_exceptions"]
        if item["code"] == "invalid_branch_reference"
    )
    assert package["gate_status"] == "blocked"
    assert issue["waivable"] is False
    assert issue["target_key"] == "bad-branch"


def test_runtime_key_fields_without_citations_block_ready(test_db):
    from src.server.scenario.module_compiler import ModuleCompiler

    graph = _graph_with_citations()
    graph["rule_triggers"] = [{"trigger": "spot_hidden"}]
    graph["style_pack"] = {"tone": "investigative"}
    graph["branches"] = [{
        "branch_id": "uncited-progression",
        "from_scene_id": "station",
        "to_scene_id": "station",
    }]
    _insert_compiler_fixture(test_db, graph=graph)
    test_db.execute("UPDATE scenario_asset_bindings SET status = 'confirmed'")
    test_db.commit()

    package = ModuleCompiler(test_db).compile("module-version-1", requested_by="admin")
    issues = {(item["code"], item["target_type"]) for item in package["quality_exceptions"]}

    assert package["gate_status"] == "blocked"
    assert ("missing_runtime_citation", "rule_trigger") in issues
    assert ("missing_runtime_citation", "style_pack") in issues
    assert ("missing_runtime_citation", "semantic_progression_rule") in issues


def test_rule_citations_fallback_without_citation_blocks_ready(test_db):
    from src.server.scenario.module_compiler import ModuleCompiler

    graph = _graph_with_citations()
    graph.pop("rule_triggers", None)
    graph["rule_citations"] = [{"rule": "spot_hidden"}]
    _insert_compiler_fixture(test_db, graph=graph)
    test_db.execute("UPDATE scenario_asset_bindings SET status = 'confirmed'")
    test_db.commit()

    package = ModuleCompiler(test_db).compile("module-version-1", requested_by="admin")
    issues = [
        item for item in package["quality_exceptions"]
        if item["code"] == "missing_runtime_citation"
        and item["target_type"] == "rule_trigger"
    ]

    assert package["gate_status"] == "blocked"
    assert issues


def test_db_pg_keeps_scenario_asset_schema_idempotent_for_existing_tables():
    from pathlib import Path

    schema = Path("src/server/db_pg.py").read_text(encoding="utf-8")

    assert "ALTER TABLE scenario_assets ADD COLUMN IF NOT EXISTS visibility" in schema
    assert "ALTER TABLE scenario_assets ADD COLUMN IF NOT EXISTS source_document_id" in schema
    assert "ALTER TABLE scenario_asset_bindings ADD COLUMN IF NOT EXISTS evidence" in schema


def test_runtime_package_api_preview_confirm_and_recompile(client, test_db):
    from src.server.scenario.module_compiler import ModuleCompiler

    setup_auth_test_data(test_db)
    _insert_compiler_fixture(test_db)
    compiler = ModuleCompiler(test_db)
    first = compiler.compile("module-version-1", requested_by="admin")
    headers = {"Authorization": f"Bearer {login(client, 'admin')}"}

    preview = client.get(
        "/api/scenarios/module-scenario/versions/module-version-1/runtime-package",
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["runtime_package_version_id"] == first["runtime_package_version_id"]
    assert preview.json()["gate_status"] == "blocked"

    missing_graph = _graph_with_citations()
    missing_graph["scenes"][0].pop("citation")
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = 'module-version-1'",
        (json.dumps(missing_graph, ensure_ascii=False),),
    )
    test_db.execute(
        "UPDATE content_items SET citation = '{}' "
        "WHERE scenario_version_id = 'module-version-1' AND item_type = 'scene'"
    )
    test_db.execute("UPDATE scenario_asset_bindings SET status = 'confirmed'")
    test_db.commit()

    recompiled = client.post(
        "/api/scenarios/module-scenario/versions/module-version-1/runtime-package/recompile",
        headers=headers,
    )
    assert recompiled.status_code == 200, recompiled.text
    issue = next(
        item for item in recompiled.json()["quality_exceptions"]
        if item["code"] == "missing_citation"
    )

    confirmed = client.post(
        "/api/scenarios/module-scenario/versions/module-version-1/runtime-package/exceptions/confirm",
        headers=headers,
        json={
            "runtime_package_version_id": recompiled.json()["runtime_package_version_id"],
            "exception_key": issue["exception_key"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["gate_status"] == "ready"
