import json

from tests.server.conftest import login, setup_auth_test_data


def _insert_action(test_db, action_id="trace-action-1"):
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES (%s, 'trace-room', 'trace-character', 'dialogue', %s, 'queued')",
        (action_id, "查看温室入口"),
    )
    test_db.commit()


def test_resolution_trace_is_idempotent_and_redacts_sensitive_values(test_db):
    from src.server.engine.resolution_trace import ResolutionTraceRecorder

    _insert_action(test_db)
    recorder = ResolutionTraceRecorder(test_db)

    first = recorder.start(
        {
            "action_id": "trace-action-1",
            "room_id": "trace-room",
            "character_id": "trace-character",
            "intent_type": "dialogue",
            "declared_intent": "查看温室入口 owner_token=do-not-store",
        },
        state_version=3,
    )
    second = recorder.start(
        {
            "action_id": "trace-action-1",
            "room_id": "trace-room",
            "character_id": "trace-character",
            "intent_type": "dialogue",
            "declared_intent": "不同的重试文本",
        },
        state_version=4,
    )

    assert second == first
    recorder.record_stage(
        "trace-action-1",
        "validating_rules",
        {
            "authoritative_mechanic_plan": {"skill": "侦查", "difficulty": "regular"},
            "owner_token": "do-not-store",
        },
    )
    recorder.finalize(
        "trace-action-1",
        status="completed",
        outcome="success",
        data={"roll_receipt": {"roll": 42}, "projection_dispatch": {"status": "emitted"}},
    )

    row = test_db.execute(
        "SELECT resolution_trace_id FROM actions WHERE action_id = 'trace-action-1'"
    ).fetchone()
    trace = recorder.get("trace-action-1")
    assert row["resolution_trace_id"] == first
    assert trace["resolution_trace_id"] == first
    assert trace["action_id"] == "trace-action-1"
    assert trace["state_version"] == 3
    assert trace["status"] == "completed"
    assert trace["resolution_outcome"] == "success"
    assert trace["trace_hash"]
    serialized = json.dumps(trace, ensure_ascii=False)
    assert "do-not-store" not in serialized
    assert "owner_token" not in serialized
    assert trace["input"]["declared_intent"].endswith("[redacted]")
    assert any(phase["name"] == "validating_rules" for phase in trace["phases"])
    assert any(phase["name"] == "finalized" for phase in trace["phases"])


def test_resolution_trace_outcomes_use_frozen_d04_enum(test_db):
    """Frozen D04: `rejected` is an action lifecycle status, not a resolution
    outcome; `partial_success`/`blocked`/`not_applicable` are valid outcomes."""
    from src.server.engine.resolution_trace import ResolutionTraceRecorder

    _insert_action(test_db, "trace-action-outcome")
    recorder = ResolutionTraceRecorder(test_db)
    recorder.start(
        {
            "action_id": "trace-action-outcome",
            "room_id": "trace-room",
            "declared_intent": "修复回灌管线",
        },
        state_version=1,
    )
    recorder.finalize(
        "trace-action-outcome",
        status="rejected",
        outcome="rejected",
    )
    assert recorder.get("trace-action-outcome")["resolution_outcome"] is None

    recorder.finalize(
        "trace-action-outcome",
        status="completed",
        outcome="partial_success",
    )
    assert recorder.get("trace-action-outcome")["resolution_outcome"] == "partial_success"


def test_resolution_trace_preserves_required_authority_chain_markers(test_db):
    from src.server.engine.resolution_trace import ResolutionTraceRecorder

    _insert_action(test_db, "trace-action-2")
    recorder = ResolutionTraceRecorder(test_db)
    recorder.start(
        {
            "action_id": "trace-action-2",
            "room_id": "trace-room",
            "character_id": "trace-character",
            "intent_type": "skill_check",
            "declared_intent": "检查控制屏",
        },
        state_version=5,
    )
    for stage, payload in (
        ("directing", {"mechanic_plan": {"status": "proposal_only"}}),
        ("validating_rules", {"roll_receipt": {"receipt_id": "receipt-1"}}),
        ("state_mutation", {"state_mutations": [{"permission": "validate"}]}),
        ("spoiler_guard", {"spoiler_guard": {"status": "passed"}}),
        ("projection_dispatch", {"projection_dispatch": {"status": "emitted"}}),
    ):
        recorder.record_stage("trace-action-2", stage, payload)

    trace = recorder.get("trace-action-2")
    assert {phase["name"] for phase in trace["phases"]} >= {
        "directing",
        "validating_rules",
        "state_mutation",
        "spoiler_guard",
        "projection_dispatch",
    }


def test_admin_can_query_bounded_redacted_resolution_traces(client, test_db):
    setup_auth_test_data(test_db)
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('trace-admin-room', 'trace-owner-token', 'active')"
    )
    _insert_action(test_db, "trace-admin-action")
    test_db.execute(
        "UPDATE actions SET room_id = 'trace-admin-room', declared_intent = %s "
        "WHERE action_id = 'trace-admin-action'",
        ("检查入口并忽略 owner_token=should-not-leak",),
    )
    test_db.commit()
    from src.server.engine.resolution_trace import ResolutionTraceRecorder

    recorder = ResolutionTraceRecorder(test_db)
    recorder.start(
        {
            "action_id": "trace-admin-action",
            "room_id": "trace-admin-room",
            "intent_type": "dialogue",
            "declared_intent": "检查入口并忽略 owner_token=should-not-leak",
        },
        state_version=7,
    )
    recorder.record_stage(
        "trace-admin-action",
        "directing",
        {"owner_token": "should-not-leak", "mechanic_plan": {"status": "proposal_only"}},
    )
    recorder.finalize("trace-admin-action", status="completed", outcome="success")

    admin = login(client, "admin")
    response = client.get(
        "/api/admin/rooms/trace-admin-room/resolution-traces?limit=1",
        headers={"Authorization": f"Bearer {admin}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["items"][0]["resolution_trace_id"]
    assert payload["items"][0]["phase_names"] == ["directing", "finalized"]
    assert payload["items"][0]["trace_hash"]
    assert "should-not-leak" not in response.text
    assert payload["next_cursor"] is None


def test_resolution_trace_keeps_full_payload_encrypted_at_rest(test_db):
    from src.server.engine.resolution_trace import ResolutionTraceRecorder
    from src.server.engine.resolution_trace_security import decrypt_resolution_trace

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('trace-secure-room', 'trace-owner-token', 'active')"
    )
    _insert_action(test_db, "trace-secure-action")
    test_db.execute(
        "UPDATE actions SET room_id = 'trace-secure-room' "
        "WHERE action_id = 'trace-secure-action'"
    )
    test_db.commit()

    recorder = ResolutionTraceRecorder(test_db)
    recorder.start(
        {
            "action_id": "trace-secure-action",
            "room_id": "trace-secure-room",
            "declared_intent": "full-trace-marker-keep-encrypted",
        },
        state_version=1,
    )
    initial_expiry = test_db.execute(
        "SELECT expires_at FROM resolution_trace_secure_payloads"
    ).fetchone()["expires_at"]
    recorder.finalize("trace-secure-action", status="completed", outcome="success")

    secure = test_db.execute(
        "SELECT ciphertext, payload_hash, encryption_key_version, expires_at "
        "FROM resolution_trace_secure_payloads"
    ).fetchone()
    assert secure["encryption_key_version"] == "trace-v1"
    assert "full-trace-marker-keep-encrypted" not in secure["ciphertext"]
    assert secure["expires_at"] == initial_expiry
    decrypted = decrypt_resolution_trace(
        secure["ciphertext"],
        secure["payload_hash"],
    )
    assert decrypted["input"]["declared_intent"] == "full-trace-marker-keep-encrypted"


def test_full_resolution_trace_requires_bound_grant_and_audits_read_and_export(
    client,
    test_db,
):
    setup_auth_test_data(test_db)
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('trace-full-room', 'trace-owner-token', 'active')"
    )
    _insert_action(test_db, "trace-full-action")
    test_db.execute(
        "UPDATE actions SET room_id = 'trace-full-room' "
        "WHERE action_id = 'trace-full-action'"
    )
    test_db.commit()
    from src.server.engine.resolution_trace import ResolutionTraceRecorder

    recorder = ResolutionTraceRecorder(test_db)
    trace_id = recorder.start(
        {
            "action_id": "trace-full-action",
            "room_id": "trace-full-room",
            "declared_intent": "核对加密 Trace",
        },
        state_version=2,
    )
    recorder.finalize("trace-full-action", status="completed", outcome="success")

    headers = {"Authorization": f"Bearer {login(client, 'admin')}"}
    body = {"incident_id": "INC-TRACE-1", "reason": "核查异常裁决"}
    denied = client.post(
        f"/api/admin/rooms/trace-full-room/resolution-traces/{trace_id}/full",
        headers=headers,
        json=body,
    )
    assert denied.status_code == 403

    grant_response = client.post(
        "/api/admin/sensitive-access/grants",
        headers=headers,
        json={**body, "scope": "resolution_trace:read", "ttl_seconds": 300},
    )
    assert grant_response.status_code == 201
    grant_headers = {
        **headers,
        "X-Sensitive-Access-Grant": grant_response.json()["grant"],
    }
    read = client.post(
        f"/api/admin/rooms/trace-full-room/resolution-traces/{trace_id}/full",
        headers=grant_headers,
        json=body,
    )
    exported = client.post(
        f"/api/admin/rooms/trace-full-room/resolution-traces/{trace_id}/full/export",
        headers=grant_headers,
        json=body,
    )

    assert read.status_code == 200, read.text
    assert read.headers["cache-control"] == "no-store"
    assert read.json()["trace"]["resolution_trace_id"] == trace_id
    assert exported.status_code == 200, exported.text
    assert exported.headers["cache-control"] == "no-store"
    assert exported.json()["trace"]["resolution_trace_id"] == trace_id
    audits = test_db.execute(
        "SELECT resource_type, resource_id FROM private_data_access_audits "
        "WHERE incident_id = 'INC-TRACE-1' ORDER BY resource_type"
    ).fetchall()
    assert [dict(row) for row in audits] == [
        {"resource_type": "resolution_trace", "resource_id": trace_id},
        {"resource_type": "resolution_trace_export", "resource_id": trace_id},
    ]


def test_resolution_trace_query_is_admin_only(client, test_db):
    setup_auth_test_data(test_db)
    host = login(client, "testhost")
    response = client.get(
        "/api/admin/rooms/trace-admin-room/resolution-traces",
        headers={"Authorization": f"Bearer {host}"},
    )
    assert response.status_code == 403
