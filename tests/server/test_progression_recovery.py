import json

import pytest


def _citation(source: str) -> dict:
    return {"source_ref": source, "source_part_id": source}


def _progression_graph() -> dict:
    return {
        "scenes": [
            {
                "scene_id": "gate",
                "name": "Gate",
                "exits": ["control", "cistern"],
                "citation": _citation("scene-gate"),
            },
            {
                "scene_id": "control",
                "name": "Control",
                "exits": ["cistern"],
                "citation": _citation("scene-control"),
            },
            {"scene_id": "cistern", "name": "Cistern", "citation": _citation("scene-cistern")},
        ],
        "facts": [
            {"fact_id": "known-fact", "text": "The pump can be isolated.", "citation": _citation("fact")},
        ],
        "clues": [
            {"clue_id": "known-clue", "name": "Pump log", "citation": _citation("clue")},
        ],
        "critical_progression": [
            {
                "progression_id": "stop-flood",
                "entry_path_ids": ["primary", "backup"],
                "ordinary_failure_can_close": True,
                "alternative_path_ids": ["backup"],
                "recovery_node_ids": ["radio-reminder"],
                "citation": _citation("critical"),
            }
        ],
        "alternative_paths": [
            {
                "path_id": "backup",
                "progression_id": "stop-flood",
                "from_scene_id": "gate",
                "target_scene_id": "control",
                "conditions": [],
                "citation": _citation("backup"),
            },
            {
                "path_id": "primary",
                "progression_id": "stop-flood",
                "from_scene_id": "gate",
                "target_scene_id": "cistern",
                "conditions": [],
                "citation": _citation("primary"),
            }
        ],
        "recovery_nodes": [
            {
                "recovery_node_id": "radio-reminder",
                "progression_id": "stop-flood",
                "from_scene_ids": ["control"],
                "target_scene_id": "cistern",
                "reveal_fact_ids": ["known-fact"],
                "reveal_clue_ids": ["known-clue"],
                "conditions": [],
                "cost_boundary": {"kind": "time", "amount": 10},
                "citation": _citation("recovery"),
            }
        ],
        "true_failure_conditions": [
            {
                "failure_id": "storm-overrun",
                "conditions": [{"kind": "event", "id": "storm_clock_expired"}],
                "citation": _citation("failure"),
            }
        ],
    }


def _compile(graph: dict) -> dict:
    from src.server.scenario.module_compiler import _build_runtime_package

    return _build_runtime_package(
        {"scenario_version_id": "progression-version", "scenario_title": "Progression"},
        graph,
        {},
        [],
        [],
        [],
        [{"template_id": "investigator", "name": "Investigator"}],
    )


def _issues(graph: dict) -> list[dict]:
    from src.server.scenario.module_compiler import _quality_exceptions

    return _quality_exceptions(
        graph,
        [],
        [],
        [],
        {},
        [],
        [{"template_id": "investigator", "name": "Investigator"}],
    )


def test_runtime_package_compiles_authoritative_progression_contract():
    graph = _progression_graph()

    rules = _compile(graph)["semantic_progression_rules"]

    assert rules["critical_progression"][0]["progression_id"] == "stop-flood"
    assert rules["alternative_paths"][0]["path_id"] == "backup"
    assert rules["recovery_nodes"][0] == graph["recovery_nodes"][0]
    assert rules["true_failure_conditions"][0]["failure_id"] == "storm-overrun"
    assert not any(issue["code"].startswith("invalid_progression") for issue in _issues(graph))


def test_runtime_package_makes_compiled_alternative_paths_executable(test_db):
    from src.server.ai.director import select_progression_recovery

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES "
        "('room-alternative-path', 'owner-alternative-path', 'active')"
    )
    test_db.commit()

    package = _compile(_progression_graph())
    rules = package["semantic_progression_rules"]

    assert {
        (
            edge.get("from_scene_id"),
            edge.get("to_scene_id"),
            edge.get("alternative_path_id"),
        )
        for edge in rules["edges"]
    } >= {
        ("gate", "control", "backup"),
        ("gate", "cistern", "primary"),
    }
    assert select_progression_recovery(
        test_db,
        "room-alternative-path",
        "gate",
        package,
    )["status"] == "path_available"


def test_alternative_path_conditions_cannot_be_bypassed_by_content_edge(test_db):
    from src.server.ai.director import select_progression_recovery
    from src.server.scenario.module_compiler import _build_runtime_package

    graph = _progression_graph()
    required_clue = {"kind": "clue", "id": "known-clue"}
    for path in graph["alternative_paths"]:
        path["conditions"] = [required_clue]
    items = [
        {
            "content_item_id": f"item-{scene_id}",
            "item_type": "scene",
            "logical_key": scene_id,
            "title": scene_id,
            "citation": _citation(f"item-{scene_id}"),
        }
        for scene_id in ("gate", "control", "cistern")
    ]
    package = _build_runtime_package(
        {"scenario_version_id": "condition-version", "scenario_title": "Conditions"},
        graph,
        {},
        items,
        [
            {
                "from_content_item_id": "item-gate",
                "to_content_item_id": "item-control",
                "relation_type": "transitions_to",
                "conditions": [],
                "citation": _citation("unconditional-content-edge"),
            }
        ],
        [],
        [{"template_id": "investigator", "name": "Investigator"}],
    )
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES "
        "('room-path-condition', 'owner-path-condition', 'active')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) VALUES "
        "('char-path-condition', 'room-path-condition', 'Player', 'token')"
    )
    test_db.commit()

    before_clue = select_progression_recovery(
        test_db,
        "room-path-condition",
        "gate",
        package,
    )
    test_db.execute(
        "INSERT INTO clues (clue_id, room_id, character_id, text) VALUES "
        "('known-clue', 'room-path-condition', 'char-path-condition', 'Pump log')"
    )
    test_db.commit()
    after_clue = select_progression_recovery(
        test_db,
        "room-path-condition",
        "gate",
        package,
    )

    assert before_clue["status"] == "no_change"
    assert after_clue["status"] == "path_available"
    assert all(
        required_clue in edge.get("conditions", [])
        for edge in package["semantic_progression_rules"]["edges"]
        if edge.get("from_scene_id") == "gate"
    )


def test_compile_gate_rejects_single_ordinary_failure_closable_critical_entry():
    graph = _progression_graph()
    graph["critical_progression"][0].update({
        "entry_path_ids": ["primary"],
        "alternative_path_ids": [],
        "recovery_node_ids": [],
    })
    graph["alternative_paths"] = []
    graph["recovery_nodes"] = []

    assert any(
        issue["code"] == "critical_progression_single_closable_entry"
        and issue["blocking"] is True
        and issue["waivable"] is False
        for issue in _issues(graph)
    )


def test_compile_gate_rejects_unsafe_recovery_nodes():
    for mutation, expected_code in (
        ({"citation": {}}, "invalid_progression_recovery_citation"),
        ({"reveal_fact_ids": ["invented-fact"]}, "invalid_progression_recovery_fact"),
        ({"reveal_clue_ids": ["invented-clue"]}, "invalid_progression_recovery_clue"),
        ({"cost_boundary": {}}, "invalid_progression_recovery_cost_boundary"),
        (
            {"cost_boundary": {"kind": "time", "amount": 0.5}},
            "invalid_progression_recovery_cost_boundary",
        ),
        ({"progression_id": "other-progression"}, "invalid_progression_recovery_owner"),
        ({"from_scene_ids": []}, "invalid_progression_recovery_scene"),
        ({"target_scene_id": ""}, "invalid_progression_recovery_scene"),
    ):
        graph = _progression_graph()
        graph["recovery_nodes"][0].update(mutation)

        assert any(issue["code"] == expected_code for issue in _issues(graph))


def test_compile_gate_rejects_missing_or_cross_progression_entry_references():
    graph = _progression_graph()
    graph["critical_progression"][0]["entry_path_ids"] = ["missing-path"]
    graph["critical_progression"][0]["alternative_path_ids"] = ["backup"]
    graph["alternative_paths"][0]["progression_id"] = "other-progression"

    codes = {issue["code"] for issue in _issues(graph)}

    assert "invalid_critical_progression_entry" in codes
    assert "invalid_progression_alternative_owner" in codes


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ({"citation": {}}, "invalid_progression_alternative_citation"),
        ({"from_scene_id": "missing-scene"}, "invalid_progression_alternative_scene"),
        ({"target_scene_id": "missing-scene"}, "invalid_progression_alternative_scene"),
        (
            {"from_scene_id": "cistern", "target_scene_id": "gate"},
            "invalid_progression_alternative_edge",
        ),
        (
            {"conditions": [{"kind": "clue", "id": "invented-clue"}]},
            "invalid_progression_alternative_condition",
        ),
    ),
)
def test_compile_gate_rejects_unreachable_alternative_paths(mutation, expected_code):
    graph = _progression_graph()
    graph["alternative_paths"][0].update(mutation)

    issues = _issues(graph)

    assert any(
        issue["code"] == expected_code
        and issue["blocking"] is True
        and issue["waivable"] is False
        for issue in issues
    )
    assert any(
        issue["code"] == "invalid_critical_progression_entry"
        and issue["target_key"] == "stop-flood:entry:backup"
        for issue in issues
    )


def test_compile_gate_rejects_uncompiled_recovery_conditions():
    graph = _progression_graph()
    graph["recovery_nodes"][0]["conditions"] = [
        {"kind": "clue", "id": "invented-clue"}
    ]

    assert any(
        issue["code"] == "invalid_progression_recovery_condition"
        and issue["blocking"] is True
        and issue["waivable"] is False
        for issue in _issues(graph)
    )


def test_exhausted_path_uses_only_compiled_legal_recovery(test_db):
    from src.server.ai.director import select_progression_recovery

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES "
        "('room-recovery', 'owner-recovery', 'active')"
    )
    test_db.commit()
    package = _compile(_progression_graph())

    decision = select_progression_recovery(
        test_db,
        "room-recovery",
        "control",
        package,
    )

    assert decision == {
        "status": "recovery",
        "validated": True,
        "fromNodeId": "control",
        "targetNodeId": "cistern",
        "recoveryNodeId": "radio-reminder",
        "citation": _citation("recovery"),
        "ruleCitation": _citation("recovery"),
        "costBoundary": {"kind": "time", "amount": 10},
    }


def test_runtime_does_not_borrow_recovery_from_another_progression(test_db):
    from src.server.ai.director import select_progression_recovery

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES "
        "('room-cross-recovery', 'owner-cross-recovery', 'active')"
    )
    test_db.commit()
    graph = _progression_graph()
    graph["recovery_nodes"][0]["progression_id"] = "other-progression"

    decision = select_progression_recovery(
        test_db,
        "room-cross-recovery",
        "control",
        _compile(graph),
    )

    assert decision["status"] == "no_change"
    assert decision["stateChanged"] is False


def test_exhausted_path_surfaces_only_revealed_facts_without_state_change(test_db):
    from src.server.ai.director import select_progression_recovery

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status, state_version) VALUES "
        "('room-no-recovery', 'owner-no-recovery', 'active', 7)"
    )
    event = test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) "
        "VALUES ('room-no-recovery', 's2c_fact_revealed', 'party', '{}') RETURNING sequence"
    ).fetchone()
    test_db.execute(
        "INSERT INTO fact_reveals "
        "(reveal_id, room_id, fact_id, fact_text, citation, audience, source_action_id, "
        "state_version, event_sequence) VALUES "
        "('reveal-known', 'room-no-recovery', 'known-fact', 'Known public fact', %s, "
        "'party', 'action-known', 7, %s)",
        (json.dumps(_citation("known")), event["sequence"]),
    )
    test_db.commit()
    package = _compile({**_progression_graph(), "recovery_nodes": []})

    decision = select_progression_recovery(
        test_db,
        "room-no-recovery",
        "control",
        package,
    )

    assert decision == {
        "status": "revealed_unresolved_facts",
        "validated": False,
        "rejected": True,
        "reason": "progression_exhausted_revealed_facts_only",
        "revealedFactIds": ["known-fact"],
        "stateChanged": False,
    }
    assert test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = 'room-no-recovery'"
    ).fetchone()["state_version"] == 7


def test_exhausted_path_with_no_recovery_or_revealed_fact_is_no_change(test_db):
    from src.server.ai.director import select_progression_recovery

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status, state_version) VALUES "
        "('room-no-information', 'owner-no-information', 'active', 11)"
    )
    test_db.commit()

    decision = select_progression_recovery(
        test_db,
        "room-no-information",
        "control",
        _compile({**_progression_graph(), "recovery_nodes": []}),
    )

    assert decision == {
        "status": "no_change",
        "validated": False,
        "rejected": True,
        "reason": "progression_exhausted_no_information",
        "revealedFactIds": [],
        "stateChanged": False,
    }
    assert test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = 'room-no-information'"
    ).fetchone()["state_version"] == 11


def test_resolution_pipeline_revalidates_compiled_recovery_before_scene_change(
    test_db,
    monkeypatch,
):
    from src.server.ai.director import select_progression_recovery
    from src.server.engine.resolution_pipeline import ResolutionPipeline
    from src.server.models import PlayerIntent

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES "
        "('room-pipeline-recovery', 'owner-pipeline-recovery', 'active')"
    )
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, version) "
        "VALUES ('room-pipeline-recovery', 'control', '[\"control\"]', 1)"
    )
    test_db.commit()
    package = _compile(_progression_graph())
    pipeline = ResolutionPipeline(test_db)
    monkeypatch.setattr(pipeline, "_runtime_package_for_room", lambda _room_id: package)
    progression = {
        key: value
        for key, value in select_progression_recovery(
            test_db,
            "room-pipeline-recovery",
            "control",
            package,
        ).items()
        if key != "status"
    }
    intent = PlayerIntent(
        action_id="action-pipeline-recovery",
        intent_type="move",
        declared_intent="Use the compiled recovery route.",
        params={
            "fromNodeId": "control",
            "targetNodeId": "cistern",
            "analysis": {"semantic_progression": progression},
        },
    )

    transition, error = pipeline._validated_generic_scene_transition(
        {"action_id": intent.action_id, "room_id": "room-pipeline-recovery"},
        intent,
    )

    assert error is None
    assert transition == {
        "from_scene_id": "control",
        "target_scene_id": "cistern",
        "citation": _citation("recovery"),
        "recovery_node_id": "radio-reminder",
        "cost_boundary": {"kind": "time", "amount": 10},
        "already_applied": False,
    }


@pytest.mark.asyncio
async def test_ai_proposed_uncompiled_clue_is_not_persisted(test_db, monkeypatch):
    from src.server.engine.resolution_pipeline import ResolutionPipeline
    from src.server.models import PlayerIntent

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES "
        "('room-uncompiled-clue', 'owner-uncompiled-clue', 'active')"
    )
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, version) "
        "VALUES ('room-uncompiled-clue', 'control', '[\"control\"]', 1)"
    )
    test_db.commit()
    pipeline = ResolutionPipeline(test_db)
    monkeypatch.setattr(
        pipeline,
        "_runtime_package_for_room",
        lambda _room_id, *, executor=None: {
            "semantic_scenes": [{"scene_id": "control", "name": "Control"}],
            "clue_dependencies": [
                {
                    "clue_id": "known-clue",
                    "name": "Known clue",
                    "scene_id": "control",
                }
            ],
        },
    )
    intent = PlayerIntent(
        action_id="action-uncompiled-clue",
        intent_type="dialogue",
        declared_intent="I discover the invented clue.",
        params={
            "director_plan": {
                "proposed_clue": {
                    "clue_id": "invented-clue",
                    "name": "Invented clue",
                }
            }
        },
    )

    discovered = await pipeline._persist_named_runtime_clues(
        {
            "action_id": intent.action_id,
            "room_id": "room-uncompiled-clue",
            "character_id": "char-uncompiled-clue",
        },
        intent,
    )

    assert discovered == []
    assert test_db.execute(
        "SELECT 1 FROM clues WHERE room_id = 'room-uncompiled-clue'"
    ).fetchone() is None
