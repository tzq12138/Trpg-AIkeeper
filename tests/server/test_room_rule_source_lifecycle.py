"""Regression coverage for retired rule sources and room-local adjudications."""

from __future__ import annotations

import importlib

import pytest

from src.server.main import app
from tests.server.conftest import login, setup_auth_test_data


class _NoopRag:
    def search(self, *_args, **_kwargs):
        return []


class _RecordingWebSocket:
    def __init__(self, app):
        self.app = app
        self.accepted = False
        self.closed: tuple[int, str] | None = None

    async def accept(self):
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed = (code, reason)

    async def receive_text(self):
        from starlette.websockets import WebSocketDisconnect

        raise WebSocketDisconnect(code=1000)

    async def send_text(self, _message: str):
        return None


def _insert_room(
    conn,
    room_id: str,
    *,
    rule_source_status: str = "ready",
    rule_source_reason: str | None = None,
    owner_account_id: str | None = None,
    owner_token: str = "owner-token",
) -> None:
    conn.execute(
        """
        INSERT INTO rooms (
            room_id, scenario_id, owner_token, owner_account_id, status,
            rule_source_status, rule_source_reason
        ) VALUES (%s, 'sc-test', %s, %s, 'lobby', %s, %s)
        """,
        (
            room_id,
            owner_token,
            owner_account_id,
            rule_source_status,
            rule_source_reason,
        ),
    )


def _insert_local_test_rule_room(conn, room_id: str = "pending-local-rule-room") -> None:
    _insert_room(conn, room_id)
    conn.execute(
        """
        INSERT INTO rule_sets (
            rule_set_id, name, slug, system, is_base, license_type, status, created_by
        ) VALUES (
            'pending-local-rule-set', 'Pending local rules', 'pending-local-rules',
            'coc7', FALSE, 'authorized', 'published', 'test'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO rule_set_versions (
            rule_set_version_id, rule_set_id, version_number, status,
            runtime_eligible, metadata, created_by
        ) VALUES (
            'pending-local-rule-version', 'pending-local-rule-set', 1, 'published',
            TRUE, '{"local_test_only": true}', 'test'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO rule_version_publication_gates (rule_set_version_id, status)
        VALUES ('pending-local-rule-version', 'ready')
        """
    )
    conn.execute(
        """
        INSERT INTO room_rule_bindings (room_id, rule_set_version_id)
        VALUES (%s, 'pending-local-rule-version')
        """,
        (room_id,),
    )
    conn.commit()


@pytest.fixture
def retired_room(client, test_db):
    setup_auth_test_data(test_db)
    _insert_room(
        test_db,
        "retired-room",
        rule_source_status="rule_source_retired",
        rule_source_reason="local_test_rule_version",
        owner_account_id="acc-host",
        owner_token="retired-owner-token",
    )
    test_db.execute(
        """
        INSERT INTO characters (
            character_id, room_id, player_name, player_token, account_id, status
        ) VALUES ('retired-player', 'retired-room', 'Player', 'retired-player-token',
                  'acc-player', 'joined')
        """
    )
    test_db.commit()
    return {
        "room_id": "retired-room",
        "owner_token": "retired-owner-token",
        "player_token": "retired-player-token",
    }


def _assert_retired(response):
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {
        "code": "rule_source_retired",
        "reason": "local_test_rule_version",
    }


def test_public_room_read_rejects_retired_rule_source(client, retired_room):
    response = client.get(f"/api/rooms/{retired_room['room_id']}")

    _assert_retired(response)


def test_host_room_access_rejects_retired_rule_source(client, retired_room):
    response = client.get(
        f"/api/host/{retired_room['room_id']}/hud",
        headers={"X-Owner-Token": retired_room["owner_token"]},
    )

    _assert_retired(response)


def test_player_character_access_rejects_retired_rule_source(client, retired_room):
    response = client.get(
        "/api/player/character",
        headers={"X-Room-Token": retired_room["player_token"]},
    )

    _assert_retired(response)


def test_player_map_routes_preserve_retired_rule_source_error(client, retired_room):
    headers = {"X-Room-Token": retired_room["player_token"]}

    legacy = client.get(f"/api/map/{retired_room['room_id']}", headers=headers)
    current = client.get(f"/api/maps/{retired_room['room_id']}", headers=headers)

    _assert_retired(legacy)
    _assert_retired(current)


def test_rag_room_authorization_rejects_retired_rule_source(
    client, retired_room, monkeypatch
):
    monkeypatch.setattr(app.state, "rag", _NoopRag(), raising=False)
    host_token = login(client, "testhost")

    response = client.post(
        "/api/rag/search",
        json={"query": "我能砸开门吗", "room_id": retired_room["room_id"]},
        headers={"Authorization": f"Bearer {host_token}"},
    )

    _assert_retired(response)


def test_starting_a_retired_room_is_rejected_before_room_state_checks(
    client, retired_room
):
    response = client.post(
        f"/api/rooms/{retired_room['room_id']}/start",
        headers={"X-Owner-Token": retired_room["owner_token"]},
    )

    _assert_retired(response)


def test_ai_turn_rejects_retired_rule_source_before_pipeline_lookup(
    client, retired_room
):
    response = client.post(
        f"/api/rooms/{retired_room['room_id']}/ai-turn",
        headers={"X-Owner-Token": retired_room["owner_token"]},
    )

    _assert_retired(response)


def test_ai_status_rejects_retired_rule_source(client, retired_room):
    response = client.get(
        f"/api/rooms/{retired_room['room_id']}/ai-status",
        headers={"X-Owner-Token": retired_room["owner_token"]},
    )

    _assert_retired(response)


def test_player_join_paths_reject_retired_rule_source(client, retired_room):
    player_token = login(client, "testplayer")
    headers = {"Authorization": f"Bearer {player_token}"}

    join_response = client.post(
        f"/api/player/rooms/{retired_room['room_id']}/join",
        headers=headers,
    )
    preflight_response = client.get(
        f"/api/player/rooms/{retired_room['room_id']}/preflight",
        headers=headers,
    )
    join_info_response = client.get(
        f"/api/player/rooms/{retired_room['room_id']}/join-info",
        headers=headers,
    )

    _assert_retired(join_response)
    _assert_retired(preflight_response)
    _assert_retired(join_info_response)


def test_join_with_character_rejects_retired_rule_source(client, retired_room):
    player_token = login(client, "testplayer")

    response = client.post(
        f"/api/player/rooms/{retired_room['room_id']}/join-with-character",
        headers={"Authorization": f"Bearer {player_token}"},
        data={
            "player_name": "Blocked player",
            "character_data": (
                '{"name":"Blocked","occupation":"Student","age":20,'
                '"attributes":{"luck":50},"skills":{},'
                '"derived_stats":{"hp":10,"san":50,"mp":10}}'
            ),
        },
    )

    _assert_retired(response)


def test_player_reconnect_and_archive_reject_retired_rule_source(client, retired_room):
    headers = {"X-Room-Token": retired_room["player_token"]}

    reconnect_response = client.get("/api/player/reconnect", headers=headers)
    archive_response = client.get("/api/player/archive", headers=headers)

    _assert_retired(reconnect_response)
    _assert_retired(archive_response)


def test_host_export_rejects_retired_rule_source(client, retired_room):
    response = client.get(
        f"/api/rooms/{retired_room['room_id']}/export?scope=full",
        headers={"X-Owner-Token": retired_room["owner_token"]},
    )

    _assert_retired(response)


def test_room_package_export_rejects_retired_rule_source(client, retired_room):
    response = client.get(
        f"/api/exports/rooms/{retired_room['room_id']}/package",
        headers={"X-Owner-Token": retired_room["owner_token"]},
    )

    _assert_retired(response)


async def test_retired_player_websocket_closes_with_rule_source_code(
    client, retired_room
):
    from src.server.main import player_ws_endpoint

    websocket = _RecordingWebSocket(client.app)
    await player_ws_endpoint(
        websocket,
        retired_room["room_id"],
        retired_room["player_token"],
    )

    assert websocket.accepted is True
    assert websocket.closed == (4009, "rule_source_retired")


async def test_retired_host_websocket_closes_with_rule_source_code(
    client, retired_room
):
    from src.server.host.router_host import host_ws_endpoint

    websocket = _RecordingWebSocket(client.app)
    await host_ws_endpoint(
        websocket,
        retired_room["room_id"],
        retired_room["owner_token"],
    )

    assert websocket.accepted is True
    assert websocket.closed == (4009, "rule_source_retired")


def test_admin_room_detail_stays_available_for_retired_rule_source(
    client, retired_room
):
    admin_token = login(client, "admin")

    response = client.get(
        f"/api/admin/rooms/{retired_room['room_id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["room_id"] == retired_room["room_id"]


def test_admin_can_delete_a_retired_room(client, retired_room):
    admin_token = login(client, "admin")

    response = client.delete(
        f"/api/admin/rooms/{retired_room['room_id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["deleted_ids"] == [retired_room["room_id"]]


def test_room_source_guard_exposes_a_stable_retirement_error(test_db):
    _insert_room(
        test_db,
        "retired-guard-room",
        rule_source_status="rule_source_retired",
        rule_source_reason="local_test_rule_version",
    )
    test_db.commit()
    lifecycle = importlib.import_module("src.server.rule_source_lifecycle")

    with pytest.raises(lifecycle.RuleSourceRetiredError) as caught:
        lifecycle.ensure_room_rule_source_available(test_db, "retired-guard-room")

    assert caught.value.detail == {
        "code": "rule_source_retired",
        "reason": "local_test_rule_version",
    }


def test_room_adjudications_are_normalized_scoped_and_sanitized(test_db):
    _insert_room(test_db, "room-a")
    _insert_room(test_db, "room-b")
    test_db.commit()
    lifecycle = importlib.import_module("src.server.rule_source_lifecycle")

    lifecycle.upsert_room_adjudication(
        test_db,
        "room-a",
        "  我能砸开门吗？！ ",
        "门锁可尝试撬开。",
        {
            "scene": "门厅",
            "visible_fact": "门锁已经生锈",
            "account_id": "acc-secret",
            "owner_token": "owner-secret",
            "player_token": "player-secret",
            "security_boundary": "原始安全边界文本",
            "unrevealed_secret": "凶手在地下室",
        },
        None,
    )
    lifecycle.upsert_room_adjudication(
        test_db,
        "room-a",
        "我能砸开门吗",
        "门锁可以撬开，但会制造声响。",
        {"scene": "门厅", "visible_fact": "门锁已经生锈"},
        None,
    )

    adjudication = lifecycle.find_room_adjudication(
        test_db,
        "room-a",
        "我能砸开门吗？",
    )

    assert adjudication["summary"] == "门锁可以撬开，但会制造声响。"
    assert adjudication["minimal_state"] == {
        "scene": "门厅",
        "visible_fact": "门锁已经生锈",
    }
    assert lifecycle.find_room_adjudication(
        test_db,
        "room-b",
        "我能砸开门吗",
    ) is None
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM room_rule_adjudications WHERE room_id = 'room-a'"
    ).fetchone()["count"] == 1


def test_retiring_local_test_rules_requires_explicit_confirmation(client, test_db):
    setup_auth_test_data(test_db)
    _insert_local_test_rule_room(test_db)

    response = client.post(
        "/api/rag/retire-local-test-rules",
        json={},
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "retire_local_test_rules_confirmation_required"
    }
    assert test_db.execute(
        "SELECT runtime_eligible FROM rule_set_versions "
        "WHERE rule_set_version_id = 'pending-local-rule-version'"
    ).fetchone() == {"runtime_eligible": True}
    assert test_db.execute(
        "SELECT rule_source_status FROM rooms WHERE room_id = 'pending-local-rule-room'"
    ).fetchone() == {"rule_source_status": "ready"}


def test_retiring_local_test_rules_requires_an_administrator(client, test_db):
    setup_auth_test_data(test_db)
    _insert_local_test_rule_room(test_db)

    response = client.post(
        "/api/rag/retire-local-test-rules",
        json={"confirm": True},
        headers={"Authorization": f"Bearer {login(client, 'testhost')}"},
    )

    assert response.status_code == 403, response.text
    assert test_db.execute(
        "SELECT runtime_eligible FROM rule_set_versions "
        "WHERE rule_set_version_id = 'pending-local-rule-version'"
    ).fetchone() == {"runtime_eligible": True}


def test_admin_retiring_local_test_rules_is_idempotent_and_blocks_old_rooms(
    client, test_db
):
    setup_auth_test_data(test_db)
    _insert_local_test_rule_room(test_db)
    headers = {"Authorization": f"Bearer {login(client, 'admin')}"}

    first = client.post(
        "/api/rag/retire-local-test-rules",
        json={"confirm": True},
        headers=headers,
    )

    assert first.status_code == 200, first.text
    assert first.json() == {
        "code": "local_test_rule_versions_retired",
        "retired_rule_versions": 1,
        "retired_rooms": 1,
    }
    assert test_db.execute(
        "SELECT rule_source_status, rule_source_reason FROM rooms "
        "WHERE room_id = 'pending-local-rule-room'"
    ).fetchone() == {
        "rule_source_status": "rule_source_retired",
        "rule_source_reason": "local_test_rule_version",
    }
    _assert_retired(client.get("/api/rooms/pending-local-rule-room"))

    repeat = client.post(
        "/api/rag/retire-local-test-rules",
        json={"confirm": True},
        headers=headers,
    )

    assert repeat.status_code == 200, repeat.text
    assert repeat.json() == {
        "code": "local_test_rule_versions_retired",
        "retired_rule_versions": 0,
        "retired_rooms": 0,
    }
