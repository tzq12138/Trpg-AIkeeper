"""V4/A07 regression tests for evidence_converter defects."""

import pytest

from src.server.scenario.benchmark_evidence import (
    collect_session_observation,
    validate_evidence_manifest,
)


def _session(session_id="probe-sim", **overrides):
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


def _action(action_id="probe-action", session_id="probe-sim", **overrides):
    action = {
        "session_id": session_id,
        "action_id": action_id,
        "action_kind": "game",
        "intent_contract_hash": "h1",
        "status": "completed",
        "outcome": "success",
        "accepted_at": "2026-09-06T00:01:00+00:00",
        "resolve_started_at": "2026-09-06T00:01:00+00:00",
        "resolved_at": "2026-09-06T00:01:01+00:00",
        "server_active_ms": 1000,
        "receipt_hash": "original-roll",
        "trace_id": "nonexistent-trace",
        "trace_hash": "unverified-hash",
    }
    action.update(overrides)
    return action


def test_manifest_blocks_incomplete_trace_manifest():
    """A07 / probe evidence_incomplete_trace: expected action has 1 but complete trace ids empty.

    A07 缺陷：expected action 有 1 条而完整 Trace ID 集合为空时，validate_evidence_manifest
    返回无错误。应返回 blocking code 'trace_incomplete_for_expected'。
    """
    manifest = dict(
        schema_version=1,
        rc_id="synthetic-reject-probe-only",
        git_commit="not-a-commit",
        run_config=dict(sessions_planned=[
            dict(session_id=f"plan-{i}", run_kind="simulation", seed="same-seed")
            for i in range(32)
        ]),
        sessions=[_session()],
        actions=[_action()],
        annotations=[],
        trace_manifest={
            "expected_action_ids": ["probe-action"],
            "complete_trace_action_ids": [],  # EMPTY → should block!
        },
        ratings={},
    )
    codes = validate_evidence_manifest(manifest)
    assert "trace_incomplete_for_expected" in codes, f"Expected blocking, got {codes}"


def test_silent_misunderstanding_with_mechanical_effect_counts():
    """A07 / probe collector_silent_misinterpretation: mechanical silent misunderstanding counts.

    A07 缺陷：机械静默误解被计成 0。期望：annotation judgment=silent_misunderstanding +
    mechanical_effect=True → silent_misinterpretation_count=1。
    """
    annotation = dict(
        action_id="probe-action",
        judgment="silent_misunderstanding",
        mechanical_effect=True,
    )
    session = dict(_session(), annotations=[annotation])
    action = _action()
    observation = collect_session_observation(session, [action], annotations=[annotation])
    assert observation.silent_misinterpretation_count == 1


def test_explicit_annotation_argument_not_overridden_by_session_annotations():
    """A07 / probe collector_explicit_annotation_argument: explicit annotation arg not overridden.

    A07 缺陷：显式传入的 clarification annotation 被计成 0（被 session["annotations"] 覆盖）。
    修复后：explicit annotation passed as argument must be counted.
    """
    explicit_clarification = dict(action_id="probe-action", judgment="clarification")
    session = _session(annotations=[])  # session 里是空注解
    action = _action()
    # 显式传 annotation 参数
    observation = collect_session_observation(session, [action], annotations=[explicit_clarification])
    assert observation.clarification_count == 1


def test_normal_technical_retry_never_counts_as_duplicate_submission():
    """A07 / probe collector_technical_retry: normal technical retry never counts as duplicate submission.

    A07 缺陷：正常 technical retry 被计成重复提交 1。修复后应为 0。
    """
    session = _session(annotations=[])
    actions = [
        _action("action-1"),
        _action("retry-record", technical_retry_of="action-1"),
    ]
    observation = collect_session_observation(session, actions)
    assert observation.accepted_actions == 1
    assert observation.duplicate_submission_count == 0


def test_complete_trace_action_ids_computed_from_manifest_data():
    """A07: compute trace_complete_actions from explicit manifest data if provided."""
    session = _session(annotations=[])
    actions = [_action("a-1", trace_id="trace-1"), _action("a-2", trace_id="trace-2")]
    complete_ids = {"trace-1"}
    observation = collect_session_observation(
        session, actions, complete_trace_action_ids=complete_ids
    )
    assert observation.trace_actions == 2
    assert observation.trace_complete_actions == 1
