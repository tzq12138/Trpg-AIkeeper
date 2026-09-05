import json
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "golden_modules"
    / "02-short-team-glass-rain"
    / "module.json"
)


def _graph():
    return json.loads(MODULE_PATH.read_text(encoding="utf-8"))["knowledge_graph"]


def test_glass_rain_declares_runtime_contract_fields():
    from src.server.scenario.module_compiler import _runtime_contract_issues

    graph = _graph()

    assert _runtime_contract_issues(graph) == []


def test_runtime_contract_blocks_scene_without_importance():
    """Frozen D21 (AIO-SCEN-001): scenes must explicitly mark importance."""
    from src.server.scenario.module_compiler import _runtime_contract_issues

    graph = _graph()
    graph["scenes"][0].pop("importance")

    issues = _runtime_contract_issues(graph)

    assert any(issue["target_key"] == "glass-gate:importance" for issue in issues)


def test_runtime_contract_blocks_scene_without_pressure_or_improv_boundary():
    from src.server.scenario.module_compiler import _runtime_contract_issues

    graph = _graph()
    graph["scenes"][0].pop("pressure_clock")
    graph["scenes"][0].pop("improv_boundaries")

    issues = _runtime_contract_issues(graph)

    assert {issue["code"] for issue in issues} >= {
        "missing_runtime_scene_field",
    }
    assert any(issue["target_key"] == "glass-gate:pressure_clock" for issue in issues)


def test_runtime_contract_blocks_npc_without_secret_refs_and_reaction_rules():
    from src.server.scenario.module_compiler import _runtime_contract_issues

    graph = _graph()
    graph["npcs"][2].pop("secret_fact_refs")
    graph["npcs"][2].pop("reaction_rules")

    issues = _runtime_contract_issues(graph)

    assert any(issue["target_key"] == "han-engineer:secret_fact_refs" for issue in issues)
    assert any(issue["target_key"] == "han-engineer:reaction_rules" for issue in issues)


def test_runtime_contract_requires_npc_d21_goal_and_attitude_field_names():
    """Frozen D21 names: goals / attitude / reaction_rules, not the legacy
    current_goal / attitude_by_character / reaction_policy names."""
    from src.server.scenario.module_compiler import _runtime_contract_issues

    graph = _graph()
    npc = graph["npcs"][2]
    assert "goals" in npc and isinstance(npc["goals"], list) and npc["goals"]
    assert "attitude" in npc and isinstance(npc["attitude"], dict)
    npc.pop("goals")

    issues = _runtime_contract_issues(graph)

    assert any(issue["target_key"] == "han-engineer:goals" for issue in issues)


def test_runtime_contract_blocks_clue_without_alternative_source_and_failure_outcome():
    from src.server.scenario.module_compiler import _runtime_contract_issues

    graph = _graph()
    graph["clues"][2].pop("alternative_sources")
    graph["clues"][2].pop("failure_outcome")

    issues = _runtime_contract_issues(graph)

    assert any(issue["target_key"] == "g17-test-sheet:alternative_sources" for issue in issues)
    assert any(issue["target_key"] == "g17-test-sheet:failure_outcome" for issue in issues)


def test_runtime_contract_blocks_core_clue_without_independent_sources():
    """Frozen D20: alternatives that reuse the single acquisition source do not
    count as independent; a source plus a compiled recovery node is acceptable."""
    from src.server.scenario.module_compiler import _runtime_contract_issues

    graph = _graph()
    clue = graph["clues"][2]  # g17-test-sheet, core
    clue["reveal_conditions"] = [{"kind": "talk", "npc_id": "han-engineer"}]
    clue["alternative_sources"] = ["han-engineer"]

    issues = _runtime_contract_issues(graph)

    assert any(issue["code"] == "core_clue_non_independent_sources" for issue in issues)

    clue["recovery_node"] = {
        "recovery_node_id": "g17-test-sheet-recovery",
        "trigger_conditions": [{"kind": "scene_entry", "scene_id": "control-room"}],
        "reveal_scope": {"private_version": True},
    }

    assert _runtime_contract_issues(graph) == []


def test_runtime_contract_blocks_core_clue_that_can_be_lost_on_one_failure():
    from src.server.scenario.module_compiler import _runtime_contract_issues

    graph = _graph()
    graph["clues"][2]["alternative_sources"] = []
    graph["clues"][2]["failure_outcome"]["preserve_core"] = False

    issues = _runtime_contract_issues(graph)

    assert any(issue["code"] == "core_clue_without_alternative_source" for issue in issues)
    assert any(issue["code"] == "core_clue_failure_can_lock" for issue in issues)


def test_runtime_contract_requires_failure_progression_and_mutual_exclusion_group():
    from src.server.scenario.module_compiler import _runtime_contract_issues

    graph = _graph()
    graph["critical_progression"][0].pop("failure_progression")
    graph["endings"][0].pop("mutual_exclusion_group")

    issues = _runtime_contract_issues(graph)

    assert any(issue["target_key"] == "glass-stop-flood:failure_progression" for issue in issues)
    assert any(issue["target_key"] == "glass-rescue:mutual_exclusion_group" for issue in issues)


def test_runtime_contract_blocks_same_group_same_priority_ending_conflict():
    """Frozen D22: endings in one mutual exclusion group must not share a
    priority, otherwise Engine selection would be ambiguous at compile time."""
    from src.server.scenario.module_compiler import _runtime_contract_issues

    graph = _graph()
    graph["endings"][1]["priority"] = graph["endings"][0]["priority"]

    issues = _runtime_contract_issues(graph)

    assert any(issue["code"] == "ending_group_priority_conflict" for issue in issues)


def test_runtime_contract_is_a_blocking_compiler_gate():
    from src.server.scenario.module_compiler import _quality_exceptions

    graph = _graph()
    graph["scenes"][0].pop("pressure_clock")

    issues = _quality_exceptions(graph, [], [], [], {}, [], [])

    assert any(
        issue["code"] == "missing_runtime_scene_field"
        and issue["blocking"] is True
        and issue["waivable"] is False
        for issue in issues
    )
