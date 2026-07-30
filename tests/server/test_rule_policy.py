import json

import pytest

from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.engine.rule_executor import RuleExecutor
from src.server.ai.ai_config import pin_room_ai_runtime
from src.server.models import MechanicCompileResult, PlayerIntent


def test_rule_policy_resolves_base_then_scenario_then_room_without_numeric_tier_overlap(test_db):
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, import_status) VALUES (?, ?, ?)",
        ("policy-sc", "Policy", "structured"),
    )
    test_db.execute(
        "INSERT INTO scenario_versions (scenario_version_id, scenario_id, version_number, status, created_by) "
        "VALUES (?, ?, ?, ?, ?)",
        ("policy-sv", "policy-sc", 1, "published", "tester"),
    )
    test_db.execute(
        "INSERT INTO rooms "
        "(room_id, scenario_id, scenario_version_id, owner_token, "
        "player_experience_version) VALUES (?, ?, ?, ?, 'v1')",
        ("policy-room", "policy-sc", "policy-sv", "token"),
    )
    for rule_set_id, version_id, slug, is_base, policy in [
        ("policy-base", "policy-base-v1", "policy-base", True, {"max_bonus_dice": 2}),
        ("policy-scenario", "policy-scenario-v1", "policy-scenario", False, {"max_bonus_dice": 1}),
        ("policy-room-set", "policy-room-v1", "policy-room", False, {"max_bonus_dice": 0}),
    ]:
        test_db.execute(
            "INSERT INTO rule_sets (rule_set_id, name, slug, system, description, is_base, "
            "license_type, status, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rule_set_id, slug, slug, "coc7", "", is_base,
                "open", "published", "tester",
            ),
        )
        test_db.execute(
            "INSERT INTO rule_set_versions (rule_set_version_id, rule_set_id, version_number, "
            "label, status, metadata, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                version_id, rule_set_id, 1, "v1", "published",
                json.dumps({"deterministic_policy": policy}), "tester",
            ),
        )
    test_db.execute(
        "INSERT INTO scenario_rule_bindings (scenario_version_id, rule_set_version_id, priority) "
        "VALUES (?, ?, ?), (?, ?, ?)",
        (
            "policy-sv", "policy-base-v1", 999999,
            "policy-sv", "policy-scenario-v1", 0,
        ),
    )
    test_db.execute(
        "INSERT INTO room_rule_bindings (room_id, rule_set_version_id, priority) VALUES (?, ?, ?)",
        ("policy-room", "policy-room-v1", 0),
    )

    policy = ResolutionPipeline(test_db)._load_rule_policy({
        "room_id": "policy-room",
        "scenario_version_id": "policy-sv",
    })

    assert policy["max_bonus_dice"] == 0
    assert [source["scope"] for source in policy["_sources"]] == [
        "base", "scenario", "room"
    ]


def test_locked_room_consumes_frozen_rule_policy_snapshot(test_db):
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, import_status) VALUES (?, ?, ?)",
        ("frozen-policy-sc", "Frozen Policy", "structured"),
    )
    test_db.execute(
        "INSERT INTO scenario_versions "
        "(scenario_version_id, scenario_id, version_number, status, created_by) "
        "VALUES (?, ?, ?, ?, ?)",
        ("frozen-policy-sv", "frozen-policy-sc", 1, "published", "tester"),
    )
    test_db.execute(
        "INSERT INTO rooms "
        "(room_id, scenario_id, scenario_version_id, owner_token) "
        "VALUES (?, ?, ?, ?)",
        (
            "frozen-policy-room",
            "frozen-policy-sc",
            "frozen-policy-sv",
            "token",
        ),
    )
    test_db.execute(
        "INSERT INTO rule_sets "
        "(rule_set_id, name, slug, system, description, is_base, "
        "license_type, status, created_by) "
        "VALUES ('frozen-policy-set', 'Frozen', 'frozen-policy', 'coc7', '', "
        "FALSE, 'open', 'published', 'tester')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions "
        "(rule_set_version_id, rule_set_id, version_number, label, status, "
        "metadata, created_by) VALUES (?, ?, 1, 'v1', 'published', ?, 'tester')",
        (
            "frozen-policy-v1",
            "frozen-policy-set",
            json.dumps({"deterministic_policy": {"max_bonus_dice": 1}}),
        ),
    )
    test_db.execute(
        "INSERT INTO scenario_rule_bindings "
        "(scenario_version_id, rule_set_version_id, priority) "
        "VALUES ('frozen-policy-sv', 'frozen-policy-v1', 100)"
    )

    pin_room_ai_runtime(
        test_db,
        "frozen-policy-room",
        scenario_version_id="frozen-policy-sv",
        runtime_package_version_id="frozen-runtime-package",
    )
    binding_row = test_db.execute(
        "SELECT state FROM host_states WHERE room_id = 'frozen-policy-room'"
    ).fetchone()
    binding_state = (
        binding_row["state"]
        if isinstance(binding_row["state"], dict)
        else json.loads(binding_row["state"])
    )
    binding = binding_state["ai_config"]["runtime_binding"]
    assert binding["compiled_rule_policy"]["policy"] == {
        "max_bonus_dice": 1,
    }
    test_db.execute(
        "UPDATE rule_set_versions SET metadata = ? "
        "WHERE rule_set_version_id = 'frozen-policy-v1'",
        (json.dumps({"deterministic_policy": {"max_bonus_dice": 2}}),),
    )
    test_db.execute(
        "DELETE FROM scenario_rule_bindings "
        "WHERE scenario_version_id = 'frozen-policy-sv'"
    )

    policy = ResolutionPipeline(test_db)._load_rule_policy({
        "room_id": "frozen-policy-room",
        "scenario_version_id": "frozen-policy-sv",
    })

    assert policy["max_bonus_dice"] == 1
    assert policy["_sources"] == [{
        "scope": "scenario",
        "rule_set_version_id": "frozen-policy-v1",
    }]
    binding["compiled_rule_policy"]["policy"]["max_bonus_dice"] = 2
    test_db.execute(
        "UPDATE host_states SET state = ? WHERE room_id = 'frozen-policy-room'",
        (json.dumps(binding_state),),
    )

    assert ResolutionPipeline(test_db)._load_rule_policy({
        "room_id": "frozen-policy-room",
        "scenario_version_id": "frozen-policy-sv",
    }) == {}


@pytest.mark.parametrize("experience_version", ["v2", "future-v3"])
def test_non_legacy_room_with_missing_frozen_rule_snapshot_fails_closed(
    test_db,
    experience_version,
):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, player_experience_version) "
        "VALUES ('missing-frozen-policy-room', 'token', %s)",
        (experience_version,),
    )
    test_db.execute(
        "INSERT INTO rule_sets "
        "(rule_set_id, name, slug, system, description, is_base, "
        "license_type, status, created_by) "
        "VALUES ('live-policy-set', 'Live', 'live-policy', 'coc7', '', "
        "TRUE, 'open', 'published', 'tester')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions "
        "(rule_set_version_id, rule_set_id, version_number, label, status, "
        "metadata, created_by) VALUES (?, ?, 1, 'v1', 'published', ?, 'tester')",
        (
            "live-policy-v1",
            "live-policy-set",
            json.dumps({"deterministic_policy": {"max_bonus_dice": 2}}),
        ),
    )
    policy = ResolutionPipeline(test_db)._load_rule_policy({
        "room_id": "missing-frozen-policy-room",
        "player_experience_version": experience_version,
    })

    assert policy == {}


@pytest.mark.asyncio
async def test_rule_executor_applies_resolved_policy_to_authoritative_roll(monkeypatch):
    values = iter([5, 0])
    monkeypatch.setattr(
        "src.server.engine.skill_check.random.randint",
        lambda _low, _high: next(values),
    )
    result = await RuleExecutor().execute(
        PlayerIntent(intent_type="skill_check", declared_intent="侦查"),
        MechanicCompileResult(
            triggeredMechanic="skill_check",
            skillName="侦查",
            consequence={"bonusDice": 2},
        ),
        {"xlsx_data": {"skills": {"侦查": 60}, "luck": 0}},
        inventory=[],
        scenario_assets={"rule_policy": {"max_bonus_dice": 0}},
    )

    assert result.metadata["bonus_dice"] == 0
    assert result.metadata["roll_trace"]["candidates"] == [50]
