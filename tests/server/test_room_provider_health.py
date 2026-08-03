import json

import pytest

from src.server.ai.gateway import AiGateway
from src.server.ai.providers import BaseAiProvider
from tests.server.conftest import create_room, setup_auth_test_data


class _PinnedProvider(BaseAiProvider):
    def __init__(self, *, fail: bool = False, healthy: bool = True):
        super().__init__("pinned")
        self.model = "model-a"
        self.fail = fail
        self.healthy = healthy
        self.calls = 0

    async def call(self, _task_type, _context):
        self.calls += 1
        if self.fail:
            raise TimeoutError("provider-private-timeout-detail")
        return {"narrative": {"public": "pinned response"}}

    async def health_check(self) -> bool:
        return self.healthy


class _LocalProvider(BaseAiProvider):
    def __init__(self):
        super().__init__("local")
        self.model = "deterministic-local"

    async def call(self, _task_type, _context):
        return {"narrative": {"public": "safe fallback"}}


def _setup_bound_room(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client)
    row = test_db.execute(
        "SELECT state FROM host_states WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    state = dict(row["state"])
    binding = dict(state["ai_config"]["runtime_binding"])
    binding.update({
        "binding_id": "binding-provider-health-v1",
        "binding_revision": 1,
        "primary_provider": "pinned",
        "primary_model": "model-a",
        "configured_provider_id": "",
        "configured_provider_signature": "",
    })
    state["ai_config"]["runtime_binding"] = binding
    test_db.execute(
        "UPDATE host_states SET state = %s WHERE room_id = %s",
        (json.dumps(state), room["room_id"]),
    )
    test_db.commit()
    return room, binding


@pytest.mark.asyncio
async def test_pinned_provider_pauses_only_after_consecutive_failure_threshold(
    client,
    test_db,
):
    room, binding = _setup_bound_room(client, test_db)
    player = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
    gateway = AiGateway(db_conn=test_db)
    gateway._providers = {
        "pinned": _PinnedProvider(fail=True),
        "local": _LocalProvider(),
    }

    first = await gateway.generate_narrative({}, room_id=room["room_id"])

    assert first.public == "safe fallback"
    health = test_db.execute(
        "SELECT binding_id, consecutive_failures, status, last_error_category "
        "FROM room_provider_health WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert health == {
        "binding_id": binding["binding_id"],
        "consecutive_failures": 1,
        "status": "healthy",
        "last_error_category": "timeout",
    }
    assert test_db.execute(
        "SELECT integrity_status FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["integrity_status"] == "healthy"

    await gateway.generate_narrative({}, room_id=room["room_id"])
    await gateway.generate_narrative({}, room_id=room["room_id"])

    assert test_db.execute(
        "SELECT integrity_status, integrity_reason FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone() == {
        "integrity_status": "paused_provider",
        "integrity_reason": "provider_unavailable",
    }
    event = test_db.execute(
        "SELECT payload FROM events WHERE room_id = %s "
        "AND event_type = 's2c_runtime_integrity_changed' "
        "ORDER BY sequence DESC LIMIT 1",
        (room["room_id"],),
    ).fetchone()
    assert event["payload"] == {
        "status": "paused_provider",
        "reasonCode": "provider_unavailable",
        "allowedActions": ["read", "export", "wait_for_recovery"],
    }
    assert "private" not in json.dumps(event, ensure_ascii=False)
    blocked = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player["player_token"]},
        json={"declared_intent": "I inspect the visible door."},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "room_provider_paused"


@pytest.mark.asyncio
async def test_successful_pinned_call_resets_consecutive_failure_window(
    client,
    test_db,
):
    room, _ = _setup_bound_room(client, test_db)
    gateway = AiGateway(db_conn=test_db)
    pinned = _PinnedProvider(fail=True)
    gateway._providers = {"pinned": pinned, "local": _LocalProvider()}

    await gateway.generate_narrative({}, room_id=room["room_id"])
    pinned.fail = False
    await gateway.generate_narrative({}, room_id=room["room_id"])

    health = test_db.execute(
        "SELECT consecutive_failures, status, last_error_category, "
        "last_success_at IS NOT NULL AS succeeded "
        "FROM room_provider_health WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert health == {
        "consecutive_failures": 0,
        "status": "healthy",
        "last_error_category": "",
        "succeeded": True,
    }


def test_paused_binding_recovery_requires_health_check_and_writes_audit(
    client,
    test_db,
):
    room, binding = _setup_bound_room(client, test_db)
    test_db.execute(
        "UPDATE rooms SET integrity_status = 'paused_provider', "
        "integrity_reason = 'provider_unavailable' WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.execute(
        "INSERT INTO room_provider_health "
        "(room_id, binding_id, consecutive_failures, status) "
        "VALUES (%s, %s, 3, 'paused')",
        (room["room_id"], binding["binding_id"]),
    )
    test_db.commit()
    gateway = AiGateway(db_conn=test_db)
    pinned = _PinnedProvider(healthy=False)
    gateway._providers = {"pinned": pinned}
    previous = client.app.state.gateway
    client.app.state.gateway = gateway
    try:
        denied = client.post(
            f"/api/rooms/{room['room_id']}/ai-provider/recover",
            headers={"X-Owner-Token": room["owner_token"]},
            json={"confirm": True, "reason": "Premature recovery"},
        )
        pinned.healthy = True
        response = client.post(
            f"/api/rooms/{room['room_id']}/ai-provider/recover",
            headers={"X-Owner-Token": room["owner_token"]},
            json={"confirm": True, "reason": "Provider connectivity restored"},
        )
    finally:
        client.app.state.gateway = previous

    assert denied.status_code == 409
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "healthy"
    assert test_db.execute(
        "SELECT integrity_status FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["integrity_status"] == "healthy"
    audit = test_db.execute(
        "SELECT action, binding_id, error_category FROM room_provider_health_audits "
        "WHERE room_id = %s ORDER BY created_at DESC LIMIT 1",
        (room["room_id"],),
    ).fetchone()
    assert audit == {
        "action": "recovered",
        "binding_id": binding["binding_id"],
        "error_category": "",
    }


def test_owner_can_read_sanitized_room_provider_status(client, test_db):
    room, binding = _setup_bound_room(client, test_db)
    test_db.execute(
        "UPDATE rooms SET integrity_status = 'paused_provider', "
        "integrity_reason = 'provider_unavailable' WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.execute(
        "INSERT INTO room_provider_health "
        "(room_id, binding_id, consecutive_failures, status, last_error_category) "
        "VALUES (%s, %s, 3, 'paused', 'timeout')",
        (room["room_id"], binding["binding_id"]),
    )
    test_db.commit()

    response = client.get(
        f"/api/rooms/{room['room_id']}/ai-provider/status",
        headers={"X-Owner-Token": room["owner_token"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "room_id": room["room_id"],
        "status": "paused_provider",
        "reason_code": "provider_unavailable",
        "primary_provider": "pinned",
        "primary_model": "model-a",
        "binding_revision": 1,
        "consecutive_failures": 3,
        "last_error_category": "timeout",
    }


def test_explicit_provider_switch_retains_old_binding_and_notifies_party(
    client,
    test_db,
):
    room, old_binding = _setup_bound_room(client, test_db)
    test_db.execute(
        "INSERT INTO ai_provider_configs "
        "(provider_config_id, name, api_base_url, protocol, model, "
        "api_key_ciphertext, key_mask, test_status, created_by, updated_by) "
        "VALUES ('switch-provider', 'Switch', 'https://example.test/v1', "
        "'responses', 'model-b', 'ciphertext', '***', 'passed', "
        "'acc-host', 'acc-host')"
    )
    test_db.commit()

    denied = client.post(
        f"/api/rooms/{room['room_id']}/ai-provider/switch",
        headers={"X-Owner-Token": room["owner_token"]},
        json={
            "provider_config_id": "switch-provider",
            "reason": "Planned provider migration",
        },
    )
    switched = client.post(
        f"/api/rooms/{room['room_id']}/ai-provider/switch",
        headers={"X-Owner-Token": room["owner_token"]},
        json={
            "provider_config_id": "switch-provider",
            "confirm": True,
            "reason": "Planned provider migration",
        },
    )

    assert denied.status_code == 400
    assert switched.status_code == 200, switched.text
    current = test_db.execute(
        "SELECT state FROM host_states WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state"]["ai_config"]["runtime_binding"]
    assert current["binding_revision"] == 2
    assert current["binding_id"] != old_binding["binding_id"]
    assert current["primary_provider"] == "configured:switch-provider"
    assert current["primary_model"] == "model-b"
    versions = test_db.execute(
        "SELECT version_number, binding FROM room_ai_runtime_binding_versions "
        "WHERE room_id = %s ORDER BY version_number",
        (room["room_id"],),
    ).fetchall()
    assert [row["version_number"] for row in versions] == [1, 2]
    assert versions[0]["binding"]["binding_id"] == old_binding["binding_id"]
    assert versions[1]["binding"]["binding_id"] == current["binding_id"]
    event = test_db.execute(
        "SELECT payload FROM events WHERE room_id = %s "
        "AND event_type = 's2c_runtime_integrity_changed' "
        "ORDER BY sequence DESC LIMIT 1",
        (room["room_id"],),
    ).fetchone()
    assert event["payload"] == {
        "status": "healthy",
        "reasonCode": "provider_binding_switched",
        "bindingRevision": 2,
    }


def test_explicit_provider_switch_supports_builtin_local_fallback(
    client,
    test_db,
):
    room, old_binding = _setup_bound_room(client, test_db)
    test_db.execute(
        "UPDATE rooms SET integrity_status = 'paused_provider', "
        "integrity_reason = 'provider_unavailable' WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()

    response = client.post(
        f"/api/rooms/{room['room_id']}/ai-provider/switch",
        headers={"X-Owner-Token": room["owner_token"]},
        json={
            "provider_config_id": "builtin:local",
            "confirm": True,
            "reason": "Use deterministic local recovery",
        },
    )

    assert response.status_code == 200, response.text
    current = test_db.execute(
        "SELECT state FROM host_states WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state"]["ai_config"]["runtime_binding"]
    assert current["binding_revision"] == 2
    assert current["binding_id"] != old_binding["binding_id"]
    assert current["primary_provider"] == "local"
    assert current["primary_model"] == "deterministic-local"
    assert current["configured_provider_id"] == ""
    assert current["configured_provider_signature"] == ""
    assert test_db.execute(
        "SELECT integrity_status FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["integrity_status"] == "healthy"
