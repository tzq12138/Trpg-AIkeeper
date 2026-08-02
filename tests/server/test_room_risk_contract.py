import json

from tests.server.conftest import create_account, login


def _raw_contract(**updates):
    contract = {
        "categories": [
            {"category": "psychological_horror", "max_level": "medium"},
            {"category": "physical_harm", "max_level": "medium"},
        ],
        "excluded_tags": ["sexual_violence", "graphic_gore", "graphic_gore"],
        "default_harm": {"scene": "medium", "npc": "medium"},
        "irreversible_controls": ["san_zero_npc_transfer"],
        "hidden_checks": {
            "allowed": True,
            "declaration_source": "compiled_rule",
        },
        "safe_alternatives": {
            "graphic_gore": "fade_to_black",
            "sexual_violence": "no_effect",
        },
        "safe_abort_rule": "glass-safe-abort",
    }
    contract.update(updates)
    return contract


def _setup_risk_room(client, test_db):
    create_account(test_db, "risk-host", "riskhost", "host")
    test_db.execute(
        "INSERT INTO scenarios "
        "(scenario_id, title, import_status, publish_status, published_version_id) "
        "VALUES ('risk-scenario', 'Risk Scenario', 'structured', 'published', 'risk-version')"
    )
    test_db.execute(
        "INSERT INTO scenario_versions "
        "(scenario_version_id, scenario_id, version_number, status, created_by) "
        "VALUES ('risk-version', 'risk-scenario', 1, 'published', 'risk-host')"
    )
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, "
        "gate_status, input_checksum, runtime_package, created_by) VALUES "
        "('risk-package', 'risk-version', 1, 'ready', 'risk', %s, 'risk-host')",
        (
            json.dumps(
                {
                    "runtime_policy": {"session_mode": "ai_only"},
                    "risk_contract": _raw_contract(),
                }
            ),
        ),
    )
    test_db.commit()
    token = login(client, "riskhost")
    room_response = client.post(
        "/api/rooms",
        headers={"Authorization": f"Bearer {token}"},
        json={"scenario_id": "risk-scenario"},
    )
    assert room_response.status_code == 200, room_response.text
    room = room_response.json()
    joined = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
    return room, joined


def _confirm_session_zero(client, player_token: str, contract_hash: str):
    headers = {"X-Room-Token": player_token}
    for step in ("character_rules", "safety", "ai_host", "private_data", "connection"):
        payload = {"confirmed": True}
        if step == "safety":
            payload["contract_hash"] = contract_hash
        response = client.post(
            f"/api/player/session-zero/{step}",
            headers=headers,
            json=payload,
        )
        assert response.status_code == 200, response.text


def test_risk_contract_normalization_and_hash_are_canonical():
    from src.server.engine.risk_contract import normalize_risk_contract

    first = normalize_risk_contract(_raw_contract())
    reordered = normalize_risk_contract(
        _raw_contract(
            categories=list(reversed(_raw_contract()["categories"])),
            excluded_tags=["graphic_gore", "sexual_violence"],
            default_harm={"npc": "medium", "scene": "medium"},
        )
    )
    changed = normalize_risk_contract(
        _raw_contract(default_harm={"npc": "high", "scene": "medium"})
    )

    assert first == reordered
    assert first["schema_version"] == "risk_contract.v1"
    assert len(first["contract_hash"]) == 64
    assert first["contract_hash"] != changed["contract_hash"]
    assert first["excluded_tags"] == ["graphic_gore", "sexual_violence"]


def test_room_freezes_runtime_risk_contract_and_exposes_only_public_summary(client, test_db):
    room, joined = _setup_risk_room(client, test_db)

    stored = test_db.execute(
        "SELECT risk_contract, risk_contract_version, risk_contract_hash "
        "FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    public_room = client.get(f"/api/rooms/{room['room_id']}").json()
    session_zero = client.get(
        "/api/player/session-zero",
        headers={"X-Room-Token": joined["player_token"]},
    ).json()
    reconnect = client.get(
        "/api/player/reconnect",
        headers={"X-Room-Token": joined["player_token"]},
    ).json()

    assert room["risk_contract_hash"] == stored["risk_contract_hash"]
    assert stored["risk_contract_version"] == "risk_contract.v1"
    assert stored["risk_contract"]["hidden_checks"]["allowed"] is True
    assert public_room["risk_contract"]["contract_hash"] == stored["risk_contract_hash"]
    assert "declaration_source" not in public_room["risk_contract"]
    assert session_zero["risk_contract"] == public_room["risk_contract"]
    assert reconnect["riskContract"] == public_room["risk_contract"]


def test_session_zero_safety_confirmation_requires_current_contract_hash(client, test_db):
    room, joined = _setup_risk_room(client, test_db)
    headers = {"X-Room-Token": joined["player_token"]}
    assert client.post(
        "/api/player/session-zero/character_rules",
        headers=headers,
        json={"confirmed": True},
    ).status_code == 200

    for payload in (
        {"confirmed": True},
        {"confirmed": True, "contract_hash": "0" * 64},
    ):
        response = client.post(
            "/api/player/session-zero/safety",
            headers=headers,
            json=payload,
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "risk_contract_hash_mismatch"

    accepted = client.post(
        "/api/player/session-zero/safety",
        headers=headers,
        json={"confirmed": True, "contract_hash": room["risk_contract_hash"]},
    )
    assert accepted.status_code == 200
    stored = test_db.execute(
        "SELECT contract_version, contract_hash FROM session_zero_confirmations "
        "WHERE room_id = %s AND character_id = %s AND step = 'safety'",
        (room["room_id"], joined["character_id"]),
    ).fetchone()
    assert dict(stored) == {
        "contract_version": "risk_contract.v1",
        "contract_hash": room["risk_contract_hash"],
    }


def test_active_room_blocks_mechanical_action_until_current_contract_is_confirmed(
    client,
    test_db,
):
    room, joined = _setup_risk_room(client, test_db)
    test_db.execute(
        "UPDATE rooms SET status = 'active' WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()
    headers = {"X-Room-Token": joined["player_token"]}

    blocked = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我检查门锁"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == {
        "code": "risk_contract_confirmation_required",
        "contract_version": "risk_contract.v1",
        "contract_hash": room["risk_contract_hash"],
    }

    _confirm_session_zero(client, joined["player_token"], room["risk_contract_hash"])
    allowed = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我检查门锁"},
    )
    assert allowed.status_code == 200, allowed.text


def test_excluded_risk_tag_stops_before_ai_and_returns_no_spoiler(client, test_db):
    room, joined = _setup_risk_room(client, test_db)
    _confirm_session_zero(client, joined["player_token"], room["risk_contract_hash"])
    test_db.execute(
        "UPDATE rooms SET status = 'active' WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()

    class _Gateway:
        called = False

        async def analyze_director_action(self, *_args, **_kwargs):
            self.called = True
            return {}

    gateway = _Gateway()
    previous = client.app.state.gateway
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": joined["player_token"]},
            json={
                "declared_intent": "我继续调查",
                "params": {
                    "riskTags": ["graphic_gore"],
                    "secretContext": "the hidden victim identity",
                },
            },
        )
    finally:
        client.app.state.gateway = previous

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "risk_contract_boundary",
        "risk_tags": ["graphic_gore"],
        "safe_alternative": "fade_to_black",
    }
    assert "hidden victim" not in response.text
    assert gateway.called is False
