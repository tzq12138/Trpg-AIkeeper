"""V3 — evidence validation and observation conversion contract tests.

These tests use minimal fixtures and never count as real-run evidence: they
pin the blocking codes and the accepted-action/technical-retry accounting of
the conversion layer so the real runner cannot silently fabricate or drop
observations.
"""

import json

import pytest

from src.server.scenario.ai_only_benchmark import BenchmarkObservation
from src.server.scenario.benchmark_evidence import (
    collect_session_observation,
    manifest_digest,
    validate_evidence_manifest,
)


def _session(session_id="sim-2-01", **overrides):
    session = {
        "session_id": session_id,
        "room_id": f"room-{session_id}",
        "run_kind": "simulation",
        "started_at": "2026-09-06T00:00:00+00:00",
        "ended_at": "2026-09-06T00:40:00+00:00",
        "player_count": 2,
        "seed": "2026090501",
        "persona": "normal",
        "eligibility": "eligible",
        "ending_type": None,
        "annotations": [],
    }
    session.update(overrides)
    return session


def _action(action_id="action-1", session_id="sim-2-01", **overrides):
    action = {
        "session_id": session_id,
        "action_id": action_id,
        "action_kind": "game",
        "intent_contract_hash": "h1",
        "status": "completed",
        "outcome": "success",
        "accepted_at": "2026-09-06T00:01:00+00:00",
        "resolve_started_at": "2026-09-06T00:01:00+00:00",
        "resolved_at": "2026-09-06T00:01:03+00:00",
        "server_active_ms": 2500,
        "receipt_hash": "rh1",
        "trace_id": "trace-1",
    }
    action.update(overrides)
    return action


def _manifest(**overrides):
    plan = [
        {
            "session_id": f"sim-2-{i:02d}",
            "run_kind": "simulation",
            "seed": f"seed-{i}",
        }
        for i in range(1, 16)
    ] + [
        {
            "session_id": f"sim-4-{i:02d}",
            "run_kind": "simulation",
            "seed": f"seed-{i}",
        }
        for i in range(16, 31)
    ] + [
        {"session_id": f"fault-{i:02d}", "run_kind": "fault", "seed": f"fseed-{i}"}
        for i in range(1, 3)
    ]
    manifest = {
        "schema_version": 1,
        "rc_id": "rc-20260905-01",
        "git_commit": "073ee1491f042e4102b1b6364d459bdee149d736",
        "run_config": {"sessions_planned": plan},
        "sessions": [_session()],
        "actions": [_action()],
        "annotations": [],
        "trace_manifest": {
            "expected_action_ids": ["action-1"],
            "complete_trace_action_ids": ["action-1"],
        },
        "ratings": {},
    }
    manifest.update(overrides)
    return manifest


def test_valid_minimal_manifest_has_no_blocks():
    assert validate_evidence_manifest(_manifest()) == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda m: m.update({"schema_version": 2}), "schema_version_mismatch"),
        (lambda m: m.update({"rc_id": ""}), "rc_id_missing"),
        (lambda m: m.update({"git_commit": ""}), "git_commit_missing"),
        (lambda m: m.__setitem__("run_config", {"sessions_planned": []}),
         "sessions_planned_below_32"),
        (lambda m: m["run_config"].__setitem__(
            "sessions_planned",
            [s for s in m["run_config"]["sessions_planned"][:2]],
        ), "sessions_planned_below_32"),
        (lambda m: m["sessions"].append(_session(session_id="sim-2-01")),
         "session_id_duplicate"),
        (lambda m: m["sessions"].append(_session(
            session_id="other-1", room_id="room-sim-2-01")), "session_room_id_duplicate"),
        (lambda m: m["sessions"].__setitem__(0, _session(seed=None)),
         "session_seed_missing"),
        (lambda m: m["actions"].append(_action(
            action_id="action-2", session_id="no-such-session")),
         "action_session_unknown"),
        (lambda m: m.__setitem__("trace_manifest", {
            "expected_action_ids": ["action-1"],
            "complete_trace_action_ids": ["action-1", "action-x"],
        }), "trace_complete_exceeds_expected"),
    ],
)
def test_manifest_blocking_codes(mutate, expected):
    manifest = _manifest()
    mutate(manifest)
    codes = validate_evidence_manifest(manifest)
    assert expected in codes, codes


def test_browser_session_requires_ratings_in_1_to_5_scale():
    manifest = _manifest()
    manifest["sessions"] = [_session(
        session_id="br-2-01", room_id="room-br", run_kind="browser", seed=None,
    )]
    manifest["actions"] = [
        _action("action-1", session_id="br-2-01"),
        _action("action-2", session_id="br-2-01"),
    ]
    manifest["trace_manifest"] = {
        "expected_action_ids": ["action-1", "action-2"],
        "complete_trace_action_ids": ["action-1", "action-2"],
    }
    codes = validate_evidence_manifest(manifest)
    assert "browser_ratings_missing" in codes, codes
    manifest["ratings"] = {"br-2-01": [
        {"rater_anonymous_id": "anon-1", "clarity": 6, "agency": 5, "atmosphere": 3},
    ]}
    codes = validate_evidence_manifest(manifest)
    assert "browser_rating_scale_invalid" in codes, codes
    manifest["ratings"] = {"br-2-01": [
        {"rater_anonymous_id": "anon-1", "clarity": 4, "agency": 5, "atmosphere": 3},
    ]}
    assert validate_evidence_manifest(manifest) == []


def test_technical_retry_never_counts_as_new_observation():
    session = _session(annotations=[])
    actions = [
        _action("action-1"),
        _action("action-2", technical_retry_of="action-1",
                receipt_hash="same-receipt"),
    ]
    observation = collect_session_observation(session, actions)
    assert observation.accepted_actions == 1
    assert observation.duplicate_submission_count == 1
    assert observation.trace_actions == 1  # one logical action, one trace


def test_excluded_action_kinds_leave_accepted_denominator():
    session = _session()
    actions = [
        _action("action-1"),
        _action("ooc-1", action_kind="ooc"),
        _action("consent-1", action_kind="consent_response"),
        _action("choice-1", action_kind="choice"),
    ]
    observation = collect_session_observation(session, actions)
    assert observation.accepted_actions == 1


def test_annotations_map_judgments_into_counts():
    session = _session(annotations=[
        {"action_id": "action-1", "judgment": "clarification"},
        {"action_id": "action-2", "judgment": "correction"},
        {"action_id": "action-3", "judgment": "unnecessary_check"},
        {"action_id": "action-4", "judgment": "none"},
    ])
    actions = [
        _action(f"action-{i}") for i in range(1, 5)
    ]
    observation = collect_session_observation(session, actions)
    assert observation.clarification_count == 1
    assert observation.player_correction_count == 1
    assert observation.unnecessary_check_count == 1


def test_latencies_sorted_and_unknowns_never_defaulted():
    session = _session()
    actions = [
        _action("action-1", server_active_ms=900),
        _action("action-2", server_active_ms=250),
        _action("action-3", server_active_ms=None),
    ]
    observation = collect_session_observation(session, actions)
    assert observation.ordinary_action_latencies_ms == (250, 900)


@pytest.mark.parametrize(
    ("actions_mutator", "expected_message"),
    [
        (lambda actions: actions.append(_action("action-1")), "action_id_duplicate_within_session"),
        (lambda actions: actions.append(_action(
            "action-x", session_id="other-session")), "action_session_mismatch"),
        (lambda actions: actions.append(_action("action-x", server_active_ms=-3)),
         "action_latency_invalid"),
        (lambda actions: actions.append(_action("action-x", accepted_at=None)),
         "action_moment_missing"),
        (lambda actions: actions.append(_action("action-x", technical_retry_of="action-x")),
         "action_retry_of_invalid"),
        (lambda actions: actions.append(_action(
            "action-x", action_kind="retransmission", retransmission_of="action-1")),
         "action_retransmission_unresolved"),
    ],
)
def test_observation_conversion_rejects_inconsistent_rows(actions_mutator, expected_message):
    session = _session()
    actions = [_action("action-1")]
    actions_mutator(actions)
    with pytest.raises(ValueError, match=expected_message):
        collect_session_observation(session, actions)


def test_session_kind_and_seed_contracts():
    with pytest.raises(ValueError, match="session_kind_invalid"):
        collect_session_observation(_session(run_kind="live"), [])
    with pytest.raises(ValueError, match="session_seed_missing"):
        collect_session_observation(_session(seed=None), [])
    observation = collect_session_observation(
        _session(run_kind="browser", seed=None), [],
    )
    assert isinstance(observation, BenchmarkObservation)


def test_digest_is_deterministic_over_raw_manifest():
    manifest = _manifest()
    assert manifest_digest(manifest) == manifest_digest(json.loads(json.dumps(manifest)))
    changed = json.loads(json.dumps(manifest))
    changed["run_config"]["sessions_planned"].append(
        {"session_id": "sim-4-31", "run_kind": "simulation", "seed": "seed-31"},
    )
    assert manifest_digest(manifest) != manifest_digest(changed)
