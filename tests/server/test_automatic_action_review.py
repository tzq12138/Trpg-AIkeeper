"""R4 slice A — automatic review acceptance with frozen evidence.

In ai_only rooms a player dispute over their OWN settled action is accepted
as a pending automatic case (201) without creating any Host queue entry or
Host event; the same idempotency key replays the same review id, different
payloads under one key conflict, someone else's action stays a 404, a still-
running action is refused with an explicit not-sealed reason, and the public
GET returns the redacted summary only.
"""

import json

from tests.server.conftest import create_room, setup_auth_test_data


def _setup_ai_only_completed_action(client, test_db):
    """Completed own action inside an ai_only room (frozen runtime policy)."""
    setup_auth_test_data(test_db)
    room = create_room(client)
    joined = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
    scenario = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    package_id = f"auto-review-pkg-{room['room_id']}"
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, "
        "gate_status, input_checksum, runtime_package, created_by) "
        "VALUES (%s, %s, 1, 'ready', 'auto-review', %s, 'test')",
        (
            package_id,
            scenario["scenario_version_id"],
            json.dumps({"runtime_policy": {"session_mode": "ai_only"}}),
        ),
    )
    test_db.execute(
        "UPDATE rooms SET runtime_package_version_id = %s WHERE room_id = %s",
        (package_id, room["room_id"]),
    )
    test_db.execute(
        "UPDATE characters SET xlsx_data = %s WHERE character_id = %s",
        (
            json.dumps({"name": "调查员", "luck": 40, "hp": 10, "san": 50, "mp": 10}),
            joined["character_id"],
        ),
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, draft_id, intent_type, "
        "declared_intent, params, status, result, idempotency_key) "
        "VALUES ('review-action', %s, %s, 'draft-review', "
        "'skill_check', '我原本想侦查门框', %s, 'completed', %s, 'action-idem-1')",
        (
            room["room_id"],
            joined["character_id"],
            json.dumps({"skillName": "侦查"}, ensure_ascii=False),
            json.dumps({"narrative": "你检查了地板"}, ensure_ascii=False),
        ),
    )
    test_db.commit()
    return room, joined


def _post_review(client, joined, objection="请重新检查这次规则解释", original_intent="", key=""):
    headers = {"X-Room-Token": joined["player_token"]}
    if key:
        headers["Idempotency-Key"] = key
    return client.post(
        "/api/player/actions/review-action/review-requests",
        headers=headers,
        json={"objection": objection, "original_intent": original_intent},
    )


def test_ai_only_review_is_accepted_pending_with_frozen_evidence(client, test_db):
    room, joined = _setup_ai_only_completed_action(client, test_db)
    before_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]

    response = _post_review(client, joined, objection="结算对象理解错了", key="idem-a-1")

    assert response.status_code == 201, response.text
    review = response.json()
    assert review["status"] == "pending"
    assert review["review_request_id"]
    assert review["ai_suggestion"]["requires_host_review"] is False
    assert review["evidence_hash"]
    # The frozen original intent (server-side) is the default review statement.
    assert review["original_intent"] == "我原本想侦查门框"

    row = test_db.execute(
        "SELECT evidence_snapshot, evidence_hash, automatic_resolution, host_resolution "
        "FROM action_review_requests WHERE review_request_id = %s",
        (review["review_request_id"],),
    ).fetchone()
    assert row["evidence_hash"] == review["evidence_hash"]
    snapshot = row["evidence_snapshot"]
    assert snapshot["action"]["declared_intent"] == "我原本想侦查门框"
    assert snapshot["room"]["room_id"] == room["room_id"]
    assert snapshot["action"]["params_hash"]
    assert snapshot["evidence_hash"] == row["evidence_hash"]
    # host_resolution stays empty: this is not a disguised manual approval.
    assert row["host_resolution"] == {}
    # No Host queue entry / Host event was created.
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events "
        "WHERE room_id = %s AND audience = 'host' "
        "AND event_type = 's2c_action_review_requested'",
        (room["room_id"],),
    ).fetchone()["count"] == 0
    # The review itself never mutates world state.
    after_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]
    assert after_version == before_version


def test_same_idempotency_key_replays_same_review_id(client, test_db):
    room, joined = _setup_ai_only_completed_action(client, test_db)
    del room
    first = _post_review(client, joined, key="idem-same-1")
    assert first.status_code == 201, first.text
    assert first.json()["created"] is True
    replay = _post_review(client, joined, key="idem-same-1")
    assert replay.status_code == 201, replay.text
    assert replay.json()["review_request_id"] == first.json()["review_request_id"]
    # A replay is explicitly marked non-created so background work is never
    # re-dispatched for it (bounded review budget stays per-case).
    assert replay.json()["created"] is False
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM action_review_requests "
        "WHERE action_id = 'review-action'",
    ).fetchone()["count"] == 1


def test_different_payload_under_one_key_conflicts(client, test_db):
    room, joined = _setup_ai_only_completed_action(client, test_db)
    del room
    first = _post_review(client, joined, objection="第一次异议", key="idem-conflict-1")
    assert first.status_code == 201, first.text
    second = _post_review(client, joined, objection="不同的异议载荷", key="idem-conflict-1")
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["code"] == "idempotency_key_conflict"


def test_other_players_action_is_404_without_existence_leak(client, test_db):
    room, joined_a = _setup_ai_only_completed_action(client, test_db)
    joined_b = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
    # Only the second player may not see the first player's action.
    headers = {"X-Room-Token": joined_b["player_token"]}
    response = client.post(
        "/api/player/actions/review-action/review-requests",
        headers=headers,
        json={"objection": "我想看别人的行动"},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "action_not_found"
    assert joined_a["character_id"] != joined_b["character_id"]


def test_get_review_returns_redacted_summary_only(client, test_db):
    room, joined = _setup_ai_only_completed_action(client, test_db)
    created = _post_review(client, joined, key="idem-get-1").json()

    response = client.get(
        f"/api/player/actions/review-action/review-requests/{created['review_request_id']}",
        headers={"X-Room-Token": joined["player_token"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review_request_id"] == created["review_request_id"]
    assert body["status"] == "pending"
    assert body["evidence_hash"] == created["evidence_hash"]
    # Full snapshot and secrets are not exposed by the public GET.
    assert "evidence_snapshot" not in body
    assert "host_resolution" not in body


def test_still_running_action_is_refused_with_not_sealed_reason(client, test_db):
    room, joined = _setup_ai_only_completed_action(client, test_db)
    del room
    test_db.execute(
        "UPDATE actions SET status = 'resolving' WHERE action_id = 'review-action'"
    )
    test_db.commit()
    response = _post_review(client, joined)
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "review_not_available"
    assert "evidence_not_sealed" in detail["reason"]


# ═══════════════════════════════════════════════════════════════════════════
# R4 slice B — run_automatic_action_review outcomes.
# ═══════════════════════════════════════════════════════════════════════════

import pytest

from src.server.engine.automatic_action_review import (
    REVIEW_MAX_ATTEMPTS,
    run_automatic_action_review,
)


class _CandidateReviewGateway:
    """Gateway stub whose review_action_intent returns one valid candidate."""

    def __init__(self):
        self.calls = 0

    async def review_action_intent(self, _context, room_id=None):
        del room_id
        self.calls += 1
        return {
            "candidateExplanation": "冻结文本的本意是检查地板而非门框。",
            "reason": "重释只基于冻结原文。",
            "conviction": "medium",
        }


@pytest.mark.parametrize(
    ("objection", "expected_code"),
    [
        ("我不喜欢这次的骰点，想重骰", "disagrees_with_dice"),
        ("我想改用别的方法来尝试", "alternative_method"),
        ("事后我知道那里是安全的", "posthoc_information"),
    ],
)
async def test_inadmissible_objections_resolve_review_rejected(
    client, test_db, objection, expected_code
):
    room, joined = _setup_ai_only_completed_action(client, test_db)
    created = _post_review(client, joined, objection=objection).json()
    before = test_db.execute(
        "SELECT runtime_status, state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()

    outcome = await run_automatic_action_review(client.app.state, test_db, created["review_request_id"])

    assert outcome["status"] == "review_rejected"
    assert outcome["reason_code"] == expected_code
    row = test_db.execute(
        "SELECT status, automatic_resolution FROM action_review_requests "
        "WHERE review_request_id = %s",
        (created["review_request_id"],),
    ).fetchone()
    assert row["status"] == "resolved"
    assert row["automatic_resolution"]["reason_code"] == expected_code
    # The room was never paused and the world state never changed.
    after = test_db.execute(
        "SELECT runtime_status, state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert after["runtime_status"] == before["runtime_status"]
    assert after["state_version"] == before["state_version"]


async def test_tampered_evidence_pauses_room_as_system_paused(client, test_db):
    room, joined = _setup_ai_only_completed_action(client, test_db)
    created = _post_review(client, joined).json()
    # Tamper with the sealed snapshot after acceptance.
    test_db.execute(
        "UPDATE action_review_requests SET evidence_snapshot = jsonb_set("
        "evidence_snapshot, '{room,state_version}', '99') "
        "WHERE review_request_id = %s",
        (created["review_request_id"],),
    )
    test_db.commit()

    outcome = await run_automatic_action_review(client.app.state, test_db, created["review_request_id"])

    assert outcome["status"] == "system_paused"
    assert outcome["reason_code"] == "evidence_not_sealed"
    room_row = test_db.execute(
        "SELECT runtime_status, integrity_reason FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert room_row["runtime_status"] == "paused_system"
    assert room_row["integrity_reason"] == "review_evidence_mismatch"


async def test_provider_unavailable_bounded_retry_then_system_paused(client, test_db):
    room, joined = _setup_ai_only_completed_action(client, test_db)
    created = _post_review(client, joined).json()
    # No gateway configured on the app state: provider unavailable.
    first = await run_automatic_action_review(client.app.state, test_db, created["review_request_id"])
    assert first["status"] == "pending_retry"
    assert first["attempt"] == 1
    row = test_db.execute(
        "SELECT status, automatic_resolution FROM action_review_requests "
        "WHERE review_request_id = %s",
        (created["review_request_id"],),
    ).fetchone()
    assert row["status"] == "pending"  # stays re-runnable
    assert row["automatic_resolution"]["review_attempts"]["count"] == 1

    for _ in range(REVIEW_MAX_ATTEMPTS - 1):
        await run_automatic_action_review(client.app.state, test_db, created["review_request_id"])

    row = test_db.execute(
        "SELECT status FROM action_review_requests WHERE review_request_id = %s",
        (created["review_request_id"],),
    ).fetchone()
    assert row["status"] == "resolved"
    room_row = test_db.execute(
        "SELECT runtime_status FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert room_row["runtime_status"] == "paused_system"


async def test_admissible_objection_with_candidate_waits_for_engine_review(client, test_db):
    room, joined = _setup_ai_only_completed_action(client, test_db)
    created = _post_review(client, joined, objection="结算对象理解错了").json()
    previous_gateway = client.app.state.gateway
    gateway = _CandidateReviewGateway()
    client.app.state.gateway = gateway
    try:
        outcome = await run_automatic_action_review(
            client.app.state, test_db, created["review_request_id"]
        )
        # A second dispatch on the same case must NOT re-run the gateway: the
        # candidate is frozen for R5 and the review budget stays per-case.
        second = await run_automatic_action_review(
            client.app.state, test_db, created["review_request_id"]
        )
    finally:
        client.app.state.gateway = previous_gateway
    assert outcome["status"] == "awaiting_engine_review"
    assert second["status"] == "known_state"
    assert gateway.calls == 1
    row = test_db.execute(
        "SELECT status, automatic_resolution FROM action_review_requests "
        "WHERE review_request_id = %s",
        (created["review_request_id"],),
    ).fetchone()
    assert row["status"] == "pending"  # R5 consumes the candidate
    assert row["automatic_resolution"]["candidate"]["reason"] == "重释只基于冻结原文。"
    assert row["automatic_resolution"]["review_attempts"]["max"] == REVIEW_MAX_ATTEMPTS
    room_row = test_db.execute(
        "SELECT runtime_status FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert room_row["runtime_status"] != "paused_system"


# ═══════════════════════════════════════════════════════════════════════════
# R5 slice A — apply_automatic_review_resolution deterministic dispositions.
# ═══════════════════════════════════════════════════════════════════════════

from src.server.engine.automatic_action_review import (
    AutomaticReviewResolutionError,
    apply_automatic_review_resolution,
)


async def _awaiting_engine_case(client, test_db):
    """One own completed ai_only action whose admissible review is awaiting
    the engine step (R4 path: admissible objection + candidate gateway)."""
    room, joined = _setup_ai_only_completed_action(client, test_db)
    created = _post_review(client, joined, objection="结算对象理解错了").json()
    previous_gateway = client.app.state.gateway
    gateway = _CandidateReviewGateway()
    client.app.state.gateway = gateway
    try:
        outcome = await run_automatic_action_review(
            client.app.state, test_db, created["review_request_id"]
        )
        assert outcome["status"] == "awaiting_engine_review"
    finally:
        client.app.state.gateway = previous_gateway
    return room, joined, created, gateway



def _apply(app_state, conn, review_request_id, resolution):
    """Engine-style invocation: sign the canonical resolution first."""
    from src.server.engine.automatic_action_review import (
        sign_automatic_review_resolution,
    )

    signed = {
        **resolution,
        "engine_signature": sign_automatic_review_resolution(
            review_request_id, resolution
        ),
    }
    return apply_automatic_review_resolution(app_state, conn, review_request_id, signed)

def _resolution(status, *, mutations=None, reason_code="review_applied", reason="x",
                expected_version=None, source_action_id="review-action",
                correction=None):
    return {
        "status": status,
        "reason_code": reason_code,
        "reason": reason,
        "source_action_id": source_action_id,
        "source_receipt_hash": "sha256-original-receipt",
        "source_state_version": 0,
        "expected_current_state_version": (
            expected_version if expected_version is not None else 0
        ),
        "mutations": mutations or [],
        "correction": correction or {},
    }


async def test_apply_upheld_closes_case_without_world_changes(client, test_db):
    room, joined, created, _gateway = await _awaiting_engine_case(client, test_db)
    before = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]
    resolution = _resolution("upheld", reason_code="no_error",
                              reason="原结算无错误，维持原判。")

    applied = _apply(client.app.state, test_db, created["review_request_id"], resolution)

    assert applied["status"] == "upheld"
    assert applied["transaction_id"] is None
    row = test_db.execute(
        "SELECT status, resolved_at, automatic_resolution FROM action_review_requests "
        "WHERE review_request_id = %s",
        (created["review_request_id"],),
    ).fetchone()
    assert row["status"] == "resolved"
    assert row["resolved_at"] is not None
    assert row["automatic_resolution"]["status"] == "upheld"
    assert row["automatic_resolution"]["reason_code"] == "no_error"
    after = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]
    assert after == before
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM compensation_transactions"
    ).fetchone()["count"] == 0


async def test_apply_explanation_corrected_appends_correction_without_state_change(
    client, test_db,
):
    room, joined, created, _gateway = await _awaiting_engine_case(client, test_db)
    before = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]
    correction = {"summary": "补充解释：原文无歧义，只是说明顺序调整。"}
    resolution = _resolution(
        "explanation_corrected",
        reason_code="explanation_clarified",
        reason="补充正确解释。",
        correction=correction,
    )

    applied = _apply(client.app.state, test_db, created["review_request_id"], resolution)

    assert applied["status"] == "explanation_corrected"
    assert applied["transaction_id"]
    row = test_db.execute(
        "SELECT transaction_id, transaction_type, status, payload, reason "
        "FROM compensation_transactions WHERE review_request_id = %s",
        (created["review_request_id"],),
    ).fetchone()
    assert row["transaction_type"] == "review_correction"
    assert row["status"] == "applied"
    assert row["payload"]["kind"] == "explanation_corrected"
    assert row["payload"]["correction"]["summary"] == correction["summary"]
    assert row["payload"]["source_action_id"] == "review-action"
    assert row["payload"]["source_receipt_hash"] == "sha256-original-receipt"
    assert row["transaction_id"] == applied["transaction_id"]
    after = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]
    assert after == before
    # The original action result/bundle are never overwritten.
    original = test_db.execute(
        "SELECT result FROM actions WHERE action_id = 'review-action'"
    ).fetchone()["result"]
    assert original["narrative"] == "你检查了地板"


async def test_apply_projection_repaired_records_correction_and_notice(client, test_db):
    room, joined, created, _gateway = await _awaiting_engine_case(client, test_db)
    resolution = _resolution(
        "projection_repaired",
        reason_code="missed_audience",
        reason="补发缺失受众的通知。",
        correction={"audience": "player", "character_id": joined["character_id"]},
    )

    applied = _apply(client.app.state, test_db, created["review_request_id"], resolution)

    assert applied["status"] == "projection_repaired"
    row = test_db.execute(
        "SELECT payload FROM compensation_transactions WHERE review_request_id = %s",
        (created["review_request_id"],),
    ).fetchone()
    assert row["payload"]["kind"] == "projection_repaired"
    assert row["payload"]["requires_redispatch"] is True
    notice = test_db.execute(
        "SELECT COUNT(*) AS count FROM events WHERE room_id = %s "
        "AND event_type = 's2c_review_projection_repair'",
        (room["room_id"],),
    ).fetchone()["count"]
    assert notice == 1
    # No world state changed and the original bundle stays untouched.
    assert test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"] == 0


async def test_apply_compensated_applies_exactly_once_with_deterministic_id(
    client, test_db,
):
    room, joined, created, _gateway = await _awaiting_engine_case(client, test_db)
    version_before = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]
    resolution = _resolution(
        "compensated",
        reason_code="state_mismatch",
        reason="原行动重复扣除了生命值，返还已核实的差额。",
        expected_version=version_before,
        mutations=[{"op": "replace", "path": "/character/hp", "value": 8}],
        correction={},
    )

    first = _apply(client.app.state, test_db, created["review_request_id"], resolution)
    # Reply lost -> retry with the identical resolution.
    replay = _apply(client.app.state, test_db, created["review_request_id"], resolution)

    assert first["status"] == "compensated"
    assert first["state_version"] == version_before + 1
    assert first["transaction_id"] == replay["transaction_id"]
    assert replay["already_applied"] is True
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM compensation_transactions "
        "WHERE review_request_id = %s",
        (created["review_request_id"],),
    ).fetchone()["count"] == 1
    row = test_db.execute(
        "SELECT status FROM action_review_requests WHERE review_request_id = %s",
        (created["review_request_id"],),
    ).fetchone()
    assert row["status"] == "resolved"
    version_after = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]
    assert version_after == version_before + 1
    runtime = test_db.execute(
        "SELECT hp FROM character_runtime_state WHERE character_id = %s AND room_id = %s",
        (joined["character_id"], room["room_id"]),
    ).fetchone()
    assert runtime["hp"] == 8


@pytest.mark.parametrize(
    "status",
    ["upheld", "explanation_corrected", "projection_repaired", "review_rejected",
     "system_paused"],
)
async def test_apply_refuses_mutations_outside_compensated(client, test_db, status):
    room, joined, created, _gateway = await _awaiting_engine_case(client, test_db)
    del room, joined
    resolution = _resolution(
        status,
        mutations=[{"op": "replace", "path": "/character/hp", "value": 8}],
    )
    with pytest.raises(AutomaticReviewResolutionError) as exc:
        _apply(client.app.state, test_db, created["review_request_id"], resolution)
    assert exc.value.code == "mutations_not_allowed"


async def test_apply_rejects_unknown_status_and_action_mismatch(client, test_db):
    room, joined, created, _gateway = await _awaiting_engine_case(client, test_db)
    bad_status = _resolution("invented_outcome")
    with pytest.raises(AutomaticReviewResolutionError) as exc:
        _apply(client.app.state, test_db, created["review_request_id"], bad_status)
    assert exc.value.code == "invalid_resolution"
    wrong_action = _resolution("upheld", source_action_id="other-action")
    with pytest.raises(AutomaticReviewResolutionError) as exc:
        _apply(client.app.state, test_db, created["review_request_id"], wrong_action)
    assert exc.value.code == "action_id_mismatch"
    row = test_db.execute(
        "SELECT status FROM action_review_requests WHERE review_request_id = %s",
        (created["review_request_id"],),
    ).fetchone()
    assert row["status"] == "pending"  # untouched by refused applies


async def test_apply_rejects_unsigned_and_tampered_resolutions(client, test_db):
    """Engine-only provenance: a resolution without the engine signature (or
    with one that no longer covers the payload) can never dispose a case."""
    room, joined, created, _gateway = await _awaiting_engine_case(client, test_db)
    resolution = _resolution("compensated",
                             reason_code="state_mismatch",
                             reason="返还误扣。",
                             mutations=[{"op": "replace", "path": "/character/hp",
                                         "value": 8}])
    # No signature at all: rejected before any status is honored.
    with pytest.raises(AutomaticReviewResolutionError) as exc:
        apply_automatic_review_resolution(
            client.app.state, test_db, created["review_request_id"], resolution
        )
    assert exc.value.code == "unverified_resolution"
    # Signature valid for the original fields, then a field is tampered with:
    # the signature no longer covers the payload and the apply is refused.
    from src.server.engine.automatic_action_review import (
        sign_automatic_review_resolution,
    )

    signed = {
        **resolution,
        "engine_signature": sign_automatic_review_resolution(
            created["review_request_id"], resolution
        ),
    }
    signed["mutations"] = [{"op": "replace", "path": "/character/hp", "value": 99}]
    with pytest.raises(AutomaticReviewResolutionError) as exc:
        apply_automatic_review_resolution(
            client.app.state, test_db, created["review_request_id"], signed
        )
    assert exc.value.code == "unverified_resolution"
    # Nothing was applied and the case is untouched.
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM compensation_transactions"
    ).fetchone()["count"] == 0
    row = test_db.execute(
        "SELECT status FROM action_review_requests WHERE review_request_id = %s",
        (created["review_request_id"],),
    ).fetchone()
    assert row["status"] == "pending"


async def test_apply_state_version_mismatch_pauses_instead_of_guessing(
    client, test_db,
):
    room, joined, created, _gateway = await _awaiting_engine_case(client, test_db)
    # World moved after the case was frozen (simulate one committed change).
    test_db.execute(
        "UPDATE rooms SET state_version = state_version + 1 WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()
    resolution = _resolution(
        "compensated",
        reason_code="state_mismatch",
        reason="返还误扣。",
        expected_version=0,
        mutations=[{"op": "replace", "path": "/character/hp", "value": 8}],
    )

    outcome = _apply(client.app.state, test_db, created["review_request_id"], resolution)

    assert outcome["status"] == "system_paused"
    assert outcome["reason_code"] == "state_version_mismatch"
    room_row = test_db.execute(
        "SELECT runtime_status, integrity_reason FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert room_row["runtime_status"] == "paused_system"
    assert room_row["integrity_reason"] == "review_state_version_mismatch"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM compensation_transactions"
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT hp FROM character_runtime_state WHERE character_id = %s AND room_id = %s",
        (joined["character_id"], room["room_id"]),
    ).fetchone() is None
