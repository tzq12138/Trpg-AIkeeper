import pytest

from tests.server.conftest import (
    create_account,
    create_room,
    create_scenario,
    login,
    setup_auth_test_data,
)


def _admin_headers(client) -> dict[str, str]:
    return {"Authorization": f"Bearer {login(client, 'admin')}"}


def _insert_character(test_db, character_id: str, room_id: str, *, account_id: str | None = None):
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, account_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        (character_id, room_id, character_id, f"token-{character_id}", account_id),
    )


def _insert_room(test_db, room_id: str, *, scenario_id: str | None = None, owner_account_id: str | None = None):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, scenario_id, owner_account_id) "
        "VALUES (%s, %s, %s, %s)",
        (room_id, f"owner-{room_id}", scenario_id, owner_account_id),
    )


def _count(test_db, table: str, where_sql: str, params: tuple[str, ...]) -> int:
    return test_db.execute(
        f"SELECT COUNT(*) AS count FROM {table} WHERE {where_sql}",
        params,
    ).fetchone()["count"]


def test_batch_delete_rooms_removes_real_collaboration_and_session_dependencies(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client, login(client))
    room_id = room["room_id"]
    character_id = "bulk-room-character"
    session_id = "bulk-room-session"
    summary_id = "bulk-room-summary"
    contract_id = "bulk-room-contract"
    _insert_character(test_db, character_id, room_id)
    test_db.execute(
        "INSERT INTO campaign_sessions (campaign_session_id, room_id, started_by_character_id) "
        "VALUES (%s, %s, %s)",
        (session_id, room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO session_summaries "
        "(session_summary_id, campaign_session_id, room_id, summary_text) VALUES (%s, %s, %s, %s)",
        (summary_id, session_id, room_id, "测试摘要"),
    )
    test_db.execute(
        "INSERT INTO collaboration_contracts "
        "(contract_id, room_id, initiator_character_id, shared_intent, expires_at) "
        "VALUES (%s, %s, %s, %s, NOW() + INTERVAL '10 minutes')",
        (contract_id, room_id, character_id, "共同调查"),
    )
    test_db.execute(
        "INSERT INTO collaboration_contract_participants (contract_id, character_id, role) "
        "VALUES (%s, %s, 'initiator')",
        (contract_id, character_id),
    )
    test_db.commit()

    response = client.post(
        "/api/admin/rooms/batch-delete",
        headers=_admin_headers(client),
        json={"ids": [room_id, "room-missing", room_id], "confirm": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["requested_ids"] == [room_id, "room-missing"]
    assert payload["deleted_ids"] == [room_id]
    assert payload["not_found_ids"] == ["room-missing"]
    assert payload["errors"] == []
    assert _count(test_db, "rooms", "room_id = %s", (room_id,)) == 0
    assert _count(test_db, "collaboration_contracts", "contract_id = %s", (contract_id,)) == 0
    assert _count(test_db, "session_summaries", "session_summary_id = %s", (summary_id,)) == 0


def test_batch_delete_characters_keeps_room_sessions_and_cleans_both_sides_of_relations(client, test_db):
    setup_auth_test_data(test_db)
    room_id = "bulk-character-room"
    character_id = "bulk-character-target"
    peer_id = "bulk-character-peer"
    contract_id = "bulk-character-contract"
    _insert_room(test_db, room_id)
    _insert_character(test_db, character_id, room_id)
    _insert_character(test_db, peer_id, room_id)
    test_db.execute(
        "INSERT INTO campaign_sessions (campaign_session_id, room_id, started_by_character_id) "
        "VALUES ('bulk-character-session', %s, %s)",
        (room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO collaboration_contracts "
        "(contract_id, room_id, initiator_character_id, shared_intent, expires_at) "
        "VALUES (%s, %s, %s, %s, NOW() + INTERVAL '10 minutes')",
        (contract_id, room_id, peer_id, "共同调查"),
    )
    test_db.execute(
        "INSERT INTO collaboration_contract_participants (contract_id, character_id, role) "
        "VALUES (%s, %s, 'invitee')",
        (contract_id, character_id),
    )
    test_db.execute(
        "INSERT INTO inventory_transfer_requests "
        "(transfer_id, room_id, item_id, from_character_id, to_character_id, item_name, quantity) "
        "VALUES ('bulk-character-transfer', %s, 'item-1', %s, %s, '线索', 1)",
        (room_id, character_id, peer_id),
    )
    test_db.commit()

    response = client.post(
        "/api/admin/characters/batch-delete",
        headers=_admin_headers(client),
        json={"ids": [character_id], "confirm": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["deleted_ids"] == [character_id]
    assert response.json()["errors"] == []
    assert _count(test_db, "characters", "character_id = %s", (character_id,)) == 0
    assert _count(test_db, "campaign_sessions", "campaign_session_id = %s", ("bulk-character-session",)) == 1
    assert test_db.execute(
        "SELECT started_by_character_id FROM campaign_sessions WHERE campaign_session_id = 'bulk-character-session'"
    ).fetchone()["started_by_character_id"] is None
    assert _count(test_db, "inventory_transfer_requests", "transfer_id = %s", ("bulk-character-transfer",)) == 0
    assert _count(test_db, "collaboration_contracts", "contract_id = %s", (contract_id,)) == 1
    assert _count(
        test_db,
        "collaboration_contract_participants",
        "contract_id = %s AND character_id = %s",
        (contract_id, character_id),
    ) == 0


def test_batch_delete_accounts_uses_character_cleanup_and_preserves_ai_audit(client, test_db):
    setup_auth_test_data(test_db)
    account_id = "bulk-delete-account"
    room_id = "bulk-account-room"
    character_id = "bulk-account-character"
    peer_id = "bulk-account-peer"
    create_account(test_db, account_id, "bulk-delete", "player")
    _insert_room(test_db, room_id, owner_account_id="acc-host")
    _insert_character(test_db, character_id, room_id, account_id=account_id)
    _insert_character(test_db, peer_id, room_id)
    test_db.execute(
        "INSERT INTO inventory_transfer_requests "
        "(transfer_id, room_id, item_id, from_character_id, to_character_id, item_name, quantity) "
        "VALUES ('bulk-account-transfer', %s, 'item-2', %s, %s, '证物', 1)",
        (room_id, character_id, peer_id),
    )
    test_db.execute(
        "INSERT INTO ai_provider_config_audits (audit_id, action, actor_id) "
        "VALUES ('bulk-account-audit', 'created', %s)",
        (account_id,),
    )
    test_db.commit()

    response = client.post(
        "/api/admin/accounts/batch-delete",
        headers=_admin_headers(client),
        json={"ids": [account_id, "acc-admin", "account-missing", account_id], "confirm": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["requested_ids"] == [account_id, "acc-admin", "account-missing"]
    assert payload["deleted_ids"] == [account_id]
    assert payload["not_found_ids"] == ["account-missing"]
    errors = {item["id"]: item for item in payload["errors"]}
    assert errors["acc-admin"]["status"] == "409"
    assert errors["acc-admin"]["error"] == "管理员账号受保护，无法删除"
    assert _count(test_db, "accounts", "account_id = %s", (account_id,)) == 0
    assert _count(test_db, "characters", "character_id = %s", (character_id,)) == 0
    assert _count(test_db, "inventory_transfer_requests", "transfer_id = %s", ("bulk-account-transfer",)) == 0
    assert _count(test_db, "ai_provider_config_audits", "audit_id = %s", ("bulk-account-audit",)) == 1


def test_batch_delete_scenarios_allows_partial_success_and_blocks_used_scenarios(client, test_db):
    setup_auth_test_data(test_db)
    create_scenario(test_db, "bulk-free-scenario", "可删除剧本")
    create_scenario(test_db, "bulk-used-scenario", "使用中剧本")
    _insert_room(test_db, "bulk-scenario-room", scenario_id="bulk-used-scenario")
    test_db.commit()

    response = client.post(
        "/api/admin/scenarios/batch-delete",
        headers=_admin_headers(client),
        json={
            "ids": ["bulk-free-scenario", "bulk-used-scenario", "scenario-missing"],
            "confirm": True,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["deleted_ids"] == ["bulk-free-scenario"]
    assert payload["not_found_ids"] == ["scenario-missing"]
    errors = {item["id"]: item for item in payload["errors"]}
    assert errors["bulk-used-scenario"]["status"] == "409"
    assert _count(test_db, "scenarios", "scenario_id = %s", ("bulk-free-scenario",)) == 0
    assert _count(test_db, "scenarios", "scenario_id = %s", ("bulk-used-scenario",)) == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/admin/rooms/batch-delete",
        "/api/admin/scenarios/batch-delete",
        "/api/admin/characters/batch-delete",
        "/api/admin/accounts/batch-delete",
    ],
)
def test_batch_delete_requires_admin_and_rejects_empty_ids(client, test_db, endpoint):
    setup_auth_test_data(test_db)

    forbidden = client.post(
        endpoint,
        headers={"Authorization": f"Bearer {login(client)}"},
        json={"ids": ["any-id"], "confirm": True},
    )
    invalid = client.post(
        endpoint,
        headers=_admin_headers(client),
        json={"ids": [], "confirm": True},
    )

    assert forbidden.status_code == 403
    assert invalid.status_code == 400


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/admin/rooms/batch-delete",
        "/api/admin/scenarios/batch-delete",
        "/api/admin/characters/batch-delete",
        "/api/admin/accounts/batch-delete",
    ],
)
@pytest.mark.parametrize("confirmation", [None, False])
def test_batch_delete_requires_explicit_backend_confirmation(
    client,
    test_db,
    endpoint,
    confirmation,
):
    setup_auth_test_data(test_db)
    payload = {"ids": ["any-id"]}
    if confirmation is not None:
        payload["confirm"] = confirmation

    response = client.post(
        endpoint,
        headers=_admin_headers(client),
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "请确认后再执行删除"
