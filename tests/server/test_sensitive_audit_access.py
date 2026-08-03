import json

from tests.server.conftest import login, setup_auth_test_data


def _admin_headers(client):
    return {"Authorization": f"Bearer {login(client, 'admin')}"}


def _seed_sensitive_archive(test_db):
    setup_auth_test_data(test_db)
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status, owner_account_id) "
        "VALUES ('sensitive-room', 'owner', 'completed', 'acc-host')"
    )
    for character_id, token, account_id in (
        ("sensitive-self", "self-token", "acc-player"),
        ("sensitive-other", "other-token", None),
    ):
        test_db.execute(
            "INSERT INTO characters "
            "(character_id, room_id, player_name, player_token, account_id, status) "
            "VALUES (%s, 'sensitive-room', %s, %s, %s, 'joined')",
            (character_id, character_id, token, account_id),
        )
    test_db.execute(
        "INSERT INTO campaign_archives "
        "(archive_id, room_id, ending_type, summary, highlights, character_arcs) "
        "VALUES ('sensitive-archive', 'sensitive-room', 'mixed', 'Public ending', "
        "'[\"Public highlight\"]', %s)",
        (json.dumps([
            {"character_id": "sensitive-self", "player_name": "Self", "private": "self arc"},
            {"character_id": "sensitive-other", "player_name": "Other", "private": "other arc"},
        ]),),
    )
    test_db.execute(
        "INSERT INTO ai_call_logs "
        "(room_id, action_id, task_type, provider, model, status, context_hash, "
        "structured_proposal, engine_validation, final_delta, error_message, record_kind) "
        "VALUES ('sensitive-room', 'sensitive-action', 'director', 'configured:test', "
        "'model-v1', 'ok', 'hash', '{\"secret\": \"proposal\"}', "
        "'{\"validated\": true}', '{\"secret\": \"delta\"}', 'private-error', "
        "'decision')"
    )
    test_db.commit()


def test_archive_projection_is_public_plus_self_only(client, test_db):
    _seed_sensitive_archive(test_db)

    response = client.get(
        "/api/player/campaign-archive",
        headers={"X-Room-Token": "self-token"},
    )
    denied = client.get(
        "/api/player/campaign-archive/arcs/sensitive-other",
        headers={"X-Room-Token": "self-token"},
    )

    assert response.status_code == 200
    assert response.json()["summary"] == "Public ending"
    assert response.json()["character_arc"]["private"] == "self arc"
    assert "other arc" not in response.text
    assert denied.status_code == 403


def test_legacy_campaign_summary_cannot_bypass_private_arc_projection(client, test_db):
    _seed_sensitive_archive(test_db)

    response = client.get(
        "/api/rooms/sensitive-room/campaign?scope=public",
        headers={"X-Room-Token": "self-token"},
    )

    assert response.status_code == 200
    assert response.json()["ending"]["character_arcs"] == [
        {
            "character_id": "sensitive-self",
            "player_name": "Self",
            "private": "self arc",
        }
    ]
    assert "other arc" not in response.text


def test_admin_ops_projection_hides_sensitive_decision_fields(client, test_db):
    _seed_sensitive_archive(test_db)

    response = client.get("/api/admin/ai/logs", headers=_admin_headers(client))

    assert response.status_code == 200
    log = response.json()["logs"][0]
    assert set(log) <= {
        "id", "decision_audit_id", "room_id", "action_id", "task_type",
        "provider", "model", "duration_ms", "status", "record_kind",
        "created_at", "expires_at",
    }
    assert "proposal" not in response.text
    assert "private-error" not in response.text


def test_admin_ai_logs_clamps_negative_limit(client, test_db):
    _seed_sensitive_archive(test_db)

    response = client.get(
        "/api/admin/ai/logs?limit=-1",
        headers=_admin_headers(client),
    )

    assert response.status_code == 200
    assert len(response.json()["logs"]) == 1


def test_admin_archive_projection_is_operational_metadata_only(client, test_db):
    _seed_sensitive_archive(test_db)

    response = client.get(
        "/api/admin/campaign-archives",
        headers=_admin_headers(client),
    )

    assert response.status_code == 200
    archive = response.json()["archives"][0]
    assert set(archive) == {"archive_id", "room_id", "ending_type", "created_at"}
    assert "Public ending" not in response.text
    assert "self arc" not in response.text


def test_admin_cannot_bypass_sensitive_projection_through_legacy_room_routes(
    client,
    test_db,
):
    _seed_sensitive_archive(test_db)
    headers = _admin_headers(client)

    responses = [
        client.get(
            "/api/rooms/sensitive-room/campaign?scope=full",
            headers=headers,
        ),
        client.get("/api/rooms/sensitive-room/events", headers=headers),
        client.get("/api/rooms/sensitive-room/timeline", headers=headers),
        client.get(
            "/api/rooms/sensitive-room/export?format=json&scope=full",
            headers=headers,
        ),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]
    assert all("other arc" not in response.text for response in responses)


def test_sensitive_read_requires_bound_grant_and_writes_access_audit(client, test_db):
    _seed_sensitive_archive(test_db)
    headers = _admin_headers(client)

    invalid_ttl = client.post(
        "/api/admin/sensitive-access/grants",
        headers=headers,
        json={
            "incident_id": "INC-INVALID",
            "reason": "invalid ttl",
            "scope": "ai_decision:read",
            "ttl_seconds": "not-a-number",
        },
    )
    assert invalid_ttl.status_code == 400

    missing_incident = client.post(
        "/api/admin/sensitive-access/grants",
        headers=headers,
        json={"reason": "debug incident", "scope": "ai_decision:read", "ttl_seconds": 300},
    )
    assert missing_incident.status_code == 400

    grant_response = client.post(
        "/api/admin/sensitive-access/grants",
        headers=headers,
        json={
            "incident_id": "INC-42",
            "reason": "debug provider mismatch",
            "scope": "ai_decision:read",
            "ttl_seconds": 300,
        },
    )
    assert grant_response.status_code == 201
    grant = grant_response.json()["grant"]

    denied = client.post(
        "/api/admin/ai/logs/1/sensitive",
        headers={**headers, "X-Sensitive-Access-Grant": grant},
        json={"incident_id": "INC-WRONG", "reason": "debug"},
    )
    allowed = client.post(
        "/api/admin/ai/logs/1/sensitive",
        headers={**headers, "X-Sensitive-Access-Grant": grant},
        json={"incident_id": "INC-42", "reason": "debug provider mismatch"},
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.headers["cache-control"] == "no-store"
    assert allowed.json()["structured_proposal"] == {"secret": "proposal"}
    audit = test_db.execute(
        "SELECT incident_id, scope, reason, resource_type, resource_id "
        "FROM private_data_access_audits WHERE incident_id = 'INC-42'"
    ).fetchone()
    assert audit == {
        "incident_id": "INC-42",
        "scope": "ai_decision:read",
        "reason": "debug provider mismatch",
        "resource_type": "ai_call_log",
        "resource_id": "1",
    }


def test_sensitive_read_of_preserved_deleted_room_audit_uses_nullable_room_link(
    client,
    test_db,
):
    setup_auth_test_data(test_db)
    test_db.execute(
        "INSERT INTO ai_call_logs "
        "(room_id, action_id, task_type, provider, model, status, record_kind) "
        "VALUES ('deleted-sensitive-room', NULL, 'analyze_director_action', "
        "'configured:test', 'model-v1', 'success', 'decision')"
    )
    log_id = test_db.execute(
        "SELECT id FROM ai_call_logs WHERE room_id = 'deleted-sensitive-room'"
    ).fetchone()["id"]
    headers = _admin_headers(client)
    grant = client.post(
        "/api/admin/sensitive-access/grants",
        headers=headers,
        json={
            "incident_id": "INC-DELETED-ROOM",
            "reason": "inspect preserved minimized audit",
            "scope": "ai_decision:read",
            "ttl_seconds": 300,
        },
    ).json()["grant"]

    response = client.post(
        f"/api/admin/ai/logs/{log_id}/sensitive",
        headers={**headers, "X-Sensitive-Access-Grant": grant},
        json={
            "incident_id": "INC-DELETED-ROOM",
            "reason": "inspect preserved minimized audit",
        },
    )

    assert response.status_code == 200
    access = test_db.execute(
        "SELECT room_id FROM private_data_access_audits "
        "WHERE incident_id = 'INC-DELETED-ROOM'"
    ).fetchone()
    assert access["room_id"] is None
