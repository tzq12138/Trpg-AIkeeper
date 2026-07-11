import json

from src.server.scenario.content_projection import ContentProjectionService


def _create_version(conn, scenario_id: str = "content-projection-scenario") -> str:
    scenario_version_id = f"{scenario_id}-v1"
    conn.execute(
        "INSERT INTO scenarios (scenario_id, title, knowledge_graph) VALUES (%s, %s, %s)",
        (scenario_id, "内容投影测试", json.dumps({})),
    )
    conn.execute(
        """
        INSERT INTO scenario_versions (
            scenario_version_id, scenario_id, version_number, status,
            knowledge_graph, quality_report, prep_package, created_by
        ) VALUES (%s, %s, 1, 'draft', %s, %s, %s, 'test-admin')
        """,
        (scenario_version_id, scenario_id, json.dumps({}), json.dumps({}), json.dumps({})),
    )
    return scenario_version_id


def test_rebuild_creates_canonical_items_edges_and_auditable_run(test_db):
    scenario_version_id = _create_version(test_db)
    graph = {
        "scenes": [
            {
                "scene_id": "station",
                "name": "北落师门车站",
                "description": "末班车即将离站。",
                "citation": {"source_ref": "p1", "page_number": 1},
            },
            {"scene_id": "bus", "name": "长途车", "description": "车厢里很安静。"},
        ],
        "npcs": [{"npc_id": "driver", "name": "司机", "role": "引路人"}],
        "clues": [{"clue_id": "ticket", "name": "残缺车票", "location": "北落师门车站"}],
        "truth": {"summary": "火焰正在追逐调查员。"},
        "endings": [{"ending_id": "escape", "name": "逃离火焰", "type": "victory"}],
        "branches": [
            {
                "branch_id": "board-bus",
                "from_scene_id": "station",
                "to_scene_id": "bus",
                "conditions": [{"kind": "clue", "id": "ticket"}],
                "citation": {"source_ref": "p2", "page_number": 2},
            }
        ],
    }

    result = ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )

    assert result["status"] == "completed"
    assert result["item_count"] == 7
    rows = test_db.execute(
        "SELECT item_type, logical_key, title, citation FROM content_items "
        "WHERE scenario_version_id = %s ORDER BY item_type, logical_key",
        (scenario_version_id,),
    ).fetchall()
    assert {(row["item_type"], row["logical_key"]) for row in rows} == {
        ("branch", "board-bus"),
        ("clue", "ticket"),
        ("ending", "escape"),
        ("npc", "driver"),
        ("scene", "bus"),
        ("scene", "station"),
        ("truth", "truth"),
    }
    station = next(row for row in rows if row["logical_key"] == "station")
    assert station["citation"]["page_number"] == 1

    edge = test_db.execute(
        "SELECT relation_type, conditions, citation FROM content_item_edges "
        "WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()
    assert edge["relation_type"] == "transitions_to"
    assert edge["conditions"] == [{"kind": "clue", "id": "ticket"}]
    assert edge["citation"]["page_number"] == 2

    run = test_db.execute(
        "SELECT projection_kind, status, input_checksum, output_checksum "
        "FROM content_projection_runs WHERE projection_run_id = %s",
        (result["projection_run_id"],),
    ).fetchone()
    assert run["projection_kind"] == "canonical_content"
    assert run["status"] == "completed"
    assert run["input_checksum"]
    assert run["output_checksum"]
    loaded = ContentProjectionService(test_db).items(scenario_version_id)
    assert loaded[0]["payload"]
    assert all(isinstance(item["citation"], dict) for item in loaded)


def test_reset_clears_only_version_projection_data(test_db):
    scenario_version_id = _create_version(test_db, "content-projection-reset")
    service = ContentProjectionService(test_db)
    service.rebuild(
        scenario_version_id,
        {"scenes": [{"scene_id": "station", "name": "车站"}]},
        requested_by="test-admin",
    )

    result = service.reset(scenario_version_id, requested_by="test-admin")

    assert result["status"] == "reset"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM content_items WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM content_item_edges WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT scenario_version_id FROM scenario_versions WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()["scenario_version_id"] == scenario_version_id


def test_rebuild_projects_solo_adventure_nodes_and_transitions(test_db):
    scenario_version_id = _create_version(test_db, "content-projection-solo")
    result = ContentProjectionService(test_db).rebuild(
        scenario_version_id,
        {
            "solo_adventure": {
                "root_node_id": "1",
                "nodes": [
                    {
                        "node_id": "1",
                        "title": "条目 1",
                        "text": "你抵达车站。",
                        "target_node_ids": ["2"],
                        "citation": {"page_number": 1},
                    },
                    {
                        "node_id": "2",
                        "title": "条目 2",
                        "text": "车门在你身后关上。",
                        "target_node_ids": [],
                        "citation": {"page_number": 2},
                    },
                ],
            }
        },
        requested_by="test-admin",
    )

    assert result["item_count"] == 2
    nodes = test_db.execute(
        "SELECT logical_key, payload, citation FROM content_items "
        "WHERE scenario_version_id = %s AND item_type = 'branch_node' ORDER BY logical_key",
        (scenario_version_id,),
    ).fetchall()
    assert [node["logical_key"] for node in nodes] == ["1", "2"]
    assert nodes[0]["payload"]["text"] == "你抵达车站。"
    assert nodes[1]["citation"]["page_number"] == 2
    assert test_db.execute(
        "SELECT relation_type FROM content_item_edges WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()["relation_type"] == "transitions_to"
