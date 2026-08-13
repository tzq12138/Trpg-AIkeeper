"""Room lifecycle tests — authenticated game flow (plan21 v2)."""

import json

import pytest
from fastapi.testclient import TestClient
from src.server.main import app
from src.server.router_auth import _hash_password


@pytest.fixture
def client_with_data(test_db):
    from src.server.engine.engine import Engine
    c = TestClient(app)
    app.state.db = test_db
    app.state.engine = Engine(test_db)

    for aid, uname, role in [
        ("acc-admin", "admin", "admin"),
        ("acc-host", "testhost", "host"),
    ]:
        test_db.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (username) DO UPDATE "
            "SET role = %s, account_id = EXCLUDED.account_id",
            (aid, uname, _hash_password("test123"), uname, role, role),
        )
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, raw_text, import_status, publish_status) "
        "VALUES ('sc-test', 'Test Scenario', 'text', 'structured', 'published')"
    )
    test_db.execute(
        "INSERT INTO scenario_versions (scenario_version_id, scenario_id, version_number, "
        "status, created_by) VALUES ('sv-test', 'sc-test', 1, 'published', 'acc-admin')"
    )
    test_db.execute(
        "UPDATE scenarios SET published_version_id = 'sv-test' WHERE scenario_id = 'sc-test'"
    )
    test_db.commit()
    return c


def _login(client, username="testhost"):
    res = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    assert res.status_code == 200, res.text
    return res.json()["token"]


def _create_room(client, token=None):
    if token is None:
        token = _login(client)
    res = client.post(
        "/api/rooms",
        json={"scenario_id": "sc-test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    return res.json()


class TestCreateRoom:
    def test_create_room_requires_auth(self, client_with_data):
        res = client_with_data.post("/api/rooms", json={"scenario_id": "sc-test"})
        assert res.status_code == 401

    def test_create_room_host_succeeds(self, client_with_data):
        token = _login(client_with_data)
        data = _create_room(client_with_data, token)
        assert data["status"] == "lobby"
        assert data["room_id"]
        assert data["owner_token"]
        assert data["scenario_id"] == "sc-test"

    def test_create_room_admin_succeeds(self, client_with_data):
        token = _login(client_with_data, "admin")
        data = _create_room(client_with_data, token)
        assert data["status"] == "lobby"
        assert data["owner_account_id"] == "acc-admin"

    def test_create_room_binds_the_current_authoritative_base_version(
        self, client_with_data, test_db, monkeypatch
    ):
        monkeypatch.setattr(
            "src.server.rule_source_lifecycle.current_authoritative_base_version",
            lambda _conn: "official-coc7-v1",
        )
        test_db.execute(
            """
            INSERT INTO rule_sets (
                rule_set_id, name, slug, system, is_base, license_type, status, created_by
            ) VALUES ('official-coc7-set', 'CoC7', 'official-coc7-current', 'coc7', TRUE,
                      'authorized', 'published', 'acc-admin')
            """
        )
        test_db.execute(
            """
            INSERT INTO rule_set_versions (
                rule_set_version_id, rule_set_id, version_number, status, runtime_eligible,
                source_sha256, created_by
            ) VALUES ('official-coc7-v1', 'official-coc7-set', 1, 'published', TRUE,
                      '22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815',
                      'acc-admin')
            """
        )
        test_db.commit()

        room = _create_room(client_with_data)

        binding = test_db.execute(
            """
            SELECT rule_set_version_id
            FROM room_rule_bindings
            WHERE room_id = %s
            """,
            (room["room_id"],),
        ).fetchone()
        assert binding == {"rule_set_version_id": "official-coc7-v1"}

    def test_create_room_rejects_when_coc7_base_exists_without_eligible_version(
        self, client_with_data, test_db, monkeypatch
    ):
        monkeypatch.setattr(
            "src.server.rule_source_lifecycle.current_authoritative_base_version",
            lambda _conn: None,
        )
        test_db.execute(
            """
            INSERT INTO rule_sets (
                rule_set_id, name, slug, system, is_base, license_type, status, created_by
            ) VALUES ('official-coc7-draft', 'CoC7', 'official-coc7-draft', 'coc7', TRUE,
                      'authorized', 'draft', 'acc-admin')
            """
        )
        test_db.commit()

        response = client_with_data.post(
            "/api/rooms",
            json={"scenario_id": "sc-test"},
            headers={"Authorization": f"Bearer {_login(client_with_data)}"},
        )

        assert response.status_code == 409, response.text
        assert response.json()["detail"] == {"code": "rule_source_unavailable"}


class TestRoomAiRuntimeBinding:
    def test_create_room_pins_ai_prompt_provider_and_rule_versions(
        self,
        client_with_data,
        test_db,
    ):
        room = _create_room(client_with_data)

        row = test_db.execute(
            "SELECT state FROM host_states WHERE room_id = %s",
            (room["room_id"],),
        ).fetchone()
        assert row is not None
        state = row["state"] if isinstance(row["state"], dict) else json.loads(row["state"])
        binding = state["ai_config"]["runtime_binding"]

        assert binding["locked"] is True
        assert binding["prompt_template_version"]
        assert len(binding["prompt_template_signature"]) == 64
        assert binding["rule_compiler_version"] == "module-compiler-v1"
        assert len(binding["compiled_rule_artifact_id"]) == 64
        assert binding["runtime_package_artifact_id"] == "sv-test"
        assert len(binding["rule_policy_signature"]) == 64
        assert isinstance(binding["rule_policy_sources"], list)
        assert binding["compiled_rule_policy"]["compiler_version"] == (
            "module-compiler-v1"
        )
        assert isinstance(binding["compiled_rule_policy"]["policy"], dict)
        assert binding["primary_provider"]
        assert "provider_order" in state["ai_config"]

    def test_create_room_rolls_back_when_runtime_binding_cannot_be_pinned(
        self,
        client_with_data,
        test_db,
        monkeypatch,
    ):
        before = test_db.execute(
            "SELECT COUNT(*) AS count FROM rooms"
        ).fetchone()["count"]

        def fail_to_pin(*_args, **_kwargs):
            raise RuntimeError("simulated binding failure")

        monkeypatch.setattr(
            "src.server.ai.ai_config.pin_room_ai_runtime",
            fail_to_pin,
        )

        with pytest.raises(RuntimeError, match="simulated binding failure"):
            _create_room(client_with_data)

        assert test_db.execute(
            "SELECT COUNT(*) AS count FROM rooms"
        ).fetchone()["count"] == before

    def test_room_ai_config_cannot_be_changed_after_runtime_binding_is_pinned(
        self,
        client_with_data,
    ):
        room = _create_room(client_with_data)

        response = client_with_data.patch(
            f"/api/rooms/{room['room_id']}/ai-config",
            headers={"X-Owner-Token": room["owner_token"]},
            json={"provider_order": "mcp,local"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "房间 AI 运行版本已固定，不能静默切换"


class TestGetRoom:
    def test_get_room_public(self, client_with_data):
        data = _create_room(client_with_data)
        res = client_with_data.get(f"/api/rooms/{data['room_id']}")
        assert res.status_code == 200
        result = res.json()
        assert result["room_id"] == data["room_id"]
        assert "owner_token" not in result

    def test_get_room_not_found(self, client_with_data):
        res = client_with_data.get("/api/rooms/nonexistent")
        assert res.status_code == 404


    def test_create_room_invalid_scenario_returns_404(self, client_with_data):
        token = _login(client_with_data)
        res = client_with_data.post(
            "/api/rooms",
            json={"scenario_id": "nonexistent"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 404


class TestScenarioOptions:
    def test_get_scenario_options_requires_auth(self, client_with_data):
        data = _create_room(client_with_data)
        res = client_with_data.get(f"/api/rooms/{data['room_id']}/scenario-options")
        assert res.status_code in (401, 403)

    def test_get_scenario_options_with_owner_token(self, client_with_data):
        data = _create_room(client_with_data)
        res = client_with_data.get(
            f"/api/rooms/{data['room_id']}/scenario-options",
            headers={"X-Owner-Token": data["owner_token"]},
        )
        assert res.status_code == 200
        result = res.json()
        assert "scenarios" in result
        assert isinstance(result["scenarios"], list)
        assert len(result["scenarios"]) >= 1

    def test_set_scenario_on_active_room_returns_409(self, client_with_data):
        data = _create_room(client_with_data)
        room_id = data["room_id"]
        # Make room active by starting it with a ready player
        client_with_data.app.state.db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, is_ready, status) "
            "VALUES ('ch-sc-sw', %s, 'Alice', 'pt-sw', true, 'joined')",
            (room_id,),
        )
        client_with_data.app.state.db.commit()
        client_with_data.post(
            f"/api/rooms/{room_id}/start",
            headers={"X-Owner-Token": data["owner_token"]},
        )
        # Now attempt to switch scenario on active room
        res = client_with_data.patch(
            f"/api/rooms/{room_id}/scenario",
            json={"scenario_id": "sc-test"},
            headers={"X-Owner-Token": data["owner_token"]},
        )
        assert res.status_code == 409

    def test_set_room_scenario_rebinds_the_target_runtime_package_snapshot(
        self, client_with_data, test_db
    ):
        room = _create_room(client_with_data)
        test_db.execute(
            "INSERT INTO scenarios (scenario_id, title, import_status, publish_status, published_version_id) "
            "VALUES ('sc-switch', 'Switch Target', 'structured', 'published', 'sv-switch')"
        )
        test_db.execute(
            "INSERT INTO scenario_versions (scenario_version_id, scenario_id, version_number, status, created_by) "
            "VALUES ('sv-switch', 'sc-switch', 1, 'published', 'acc-admin')"
        )
        for package_id, version_number in [
            ("switch-runtime-v1", 1),
            ("switch-runtime-v2", 2),
        ]:
            test_db.execute(
                "INSERT INTO runtime_package_versions "
                "(runtime_package_version_id, scenario_version_id, package_version_number, gate_status, "
                "input_checksum, runtime_package, created_by) "
                "VALUES (%s, 'sv-switch', %s, 'ready', 'sha', '{}', 'test')",
                (package_id, version_number),
            )
        test_db.commit()

        response = client_with_data.patch(
            f"/api/rooms/{room['room_id']}/scenario",
            json={"scenario_id": "sc-switch"},
            headers={"X-Owner-Token": room["owner_token"]},
        )

        assert response.status_code == 200, response.text
        stored = test_db.execute(
            "SELECT scenario_id, scenario_version_id, runtime_package_version_id "
            "FROM rooms WHERE room_id = %s",
            (room["room_id"],),
        ).fetchone()
        assert dict(stored) == {
            "scenario_id": "sc-switch",
            "scenario_version_id": "sv-switch",
            "runtime_package_version_id": "switch-runtime-v2",
        }

    def test_generic_room_update_rebinds_the_target_runtime_package_snapshot(
        self, client_with_data, test_db
    ):
        room = _create_room(client_with_data)
        test_db.execute(
            "INSERT INTO scenarios (scenario_id, title, import_status, publish_status, published_version_id) "
            "VALUES ('sc-generic-switch', 'Generic Switch Target', 'structured', 'published', 'sv-generic-switch')"
        )
        test_db.execute(
            "INSERT INTO scenario_versions (scenario_version_id, scenario_id, version_number, status, created_by) "
            "VALUES ('sv-generic-switch', 'sc-generic-switch', 1, 'published', 'acc-admin')"
        )
        test_db.execute(
            "INSERT INTO runtime_package_versions "
            "(runtime_package_version_id, scenario_version_id, package_version_number, gate_status, "
            "input_checksum, runtime_package, created_by) "
            "VALUES ('generic-switch-runtime', 'sv-generic-switch', 1, 'ready', 'sha', '{}', 'test')"
        )
        test_db.commit()

        response = client_with_data.patch(
            f"/api/rooms/{room['room_id']}",
            json={"scenario_id": "sc-generic-switch"},
            headers={"X-Owner-Token": room["owner_token"]},
        )

        assert response.status_code == 200, response.text
        stored = test_db.execute(
            "SELECT runtime_package_version_id FROM rooms WHERE room_id = %s",
            (room["room_id"],),
        ).fetchone()
        assert stored["runtime_package_version_id"] == "generic-switch-runtime"


class TestPublishedScenarioRequirement:
    def test_scenario_create_room_binds_latest_ready_runtime_package_snapshot(
        self, client_with_data, test_db
    ):
        for package_id, version_number in [
            ("scenario-route-runtime-v1", 1),
            ("scenario-route-runtime-v2", 2),
        ]:
            test_db.execute(
                "INSERT INTO runtime_package_versions "
                "(runtime_package_version_id, scenario_version_id, package_version_number, gate_status, "
                "input_checksum, runtime_package, created_by) "
                "VALUES (%s, 'sv-test', %s, 'ready', 'sha', '{}', 'test')",
                (package_id, version_number),
            )
        test_db.commit()

        response = client_with_data.post(
            "/api/scenarios/sc-test/create-room",
            json={},
            headers={"Authorization": f"Bearer {_login(client_with_data)}"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["runtime_package_version_id"] == "scenario-route-runtime-v2"
        stored = test_db.execute(
            "SELECT runtime_package_version_id FROM rooms WHERE room_id = %s",
            (response.json()["room_id"],),
        ).fetchone()
        assert stored["runtime_package_version_id"] == "scenario-route-runtime-v2"

    def test_create_room_rejects_unpublished_structured_scenario(
        self, client_with_data, test_db
    ):
        _insert_unpublished_structured_scenario(test_db)
        token = _login(client_with_data)

        response = client_with_data.post(
            "/api/rooms",
            json={"scenario_id": "sc-unpublished"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 409

    def test_scenario_lists_exclude_unpublished_structured_scenario(
        self, client_with_data, test_db
    ):
        _insert_unpublished_structured_scenario(test_db)
        room = _create_room(client_with_data)
        options = client_with_data.get(
            f"/api/rooms/{room['room_id']}/scenario-options",
            headers={"X-Owner-Token": room["owner_token"]},
        )
        token = _login(client_with_data)
        available = client_with_data.get(
            "/api/scenarios/available",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert options.status_code == 200, options.text
        assert available.status_code == 200, available.text
        assert "sc-unpublished" not in {
            item["scenario_id"] for item in options.json()["scenarios"]
        }
        assert "sc-unpublished" not in {
            item["scenario_id"] for item in available.json()
        }

    def test_room_scenario_updates_reject_unpublished_structured_scenario(
        self, client_with_data, test_db
    ):
        _insert_unpublished_structured_scenario(test_db)
        room = _create_room(client_with_data)
        headers = {"X-Owner-Token": room["owner_token"]}

        dedicated = client_with_data.patch(
            f"/api/rooms/{room['room_id']}/scenario",
            json={"scenario_id": "sc-unpublished"},
            headers=headers,
        )
        generic = client_with_data.patch(
            f"/api/rooms/{room['room_id']}",
            json={"scenario_id": "sc-unpublished"},
            headers=headers,
        )

        assert dedicated.status_code == 409
        assert generic.status_code == 409

    def test_scenario_create_room_rejects_unpublished_structured_scenario(
        self, client_with_data, test_db
    ):
        _insert_unpublished_structured_scenario(test_db)
        token = _login(client_with_data)

        response = client_with_data.post(
            "/api/scenarios/sc-unpublished/create-room",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 409


class TestStartRoom:
    def test_start_room_with_owner_token(self, client_with_data):
        data = _create_room(client_with_data)
        # Add a ready player — empty room start is now rejected
        client_with_data.app.state.db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, is_ready, status) "
            "VALUES ('ch-start', %s, 'Alice', 'ptok', true, 'joined')",
            (data['room_id'],),
        )
        client_with_data.app.state.db.commit()
        res = client_with_data.post(
            f"/api/rooms/{data['room_id']}/start",
            headers={"X-Owner-Token": data["owner_token"]},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "active"

    def test_start_room_empty_returns_409(self, client_with_data):
        data = _create_room(client_with_data)
        res = client_with_data.post(
            f"/api/rooms/{data['room_id']}/start",
            headers={"X-Owner-Token": data["owner_token"]},
        )
        assert res.status_code == 409
        assert "至少需要一名玩家" in res.json()["detail"]

    def test_start_room_wrong_owner(self, client_with_data):
        data = _create_room(client_with_data)
        res = client_with_data.post(
            f"/api/rooms/{data['room_id']}/start",
            headers={"X-Owner-Token": "wrong-token"},
        )
        assert res.status_code == 403

    def test_start_creates_first_turn(self, client_with_data):
        data = _create_room(client_with_data)
        room_id = data["room_id"]
        db = client_with_data.app.state.db
        db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, is_ready, status) "
            "VALUES ('ch-turn', %s, 'Alice', 'pt-turn', true, 'joined')",
            (room_id,),
        )
        db.commit()
        res = client_with_data.post(
            f"/api/rooms/{room_id}/start",
            headers={"X-Owner-Token": data["owner_token"]},
        )
        assert res.status_code == 200
        result = res.json()
        assert result["status"] == "active"
        assert result["turn_id"]
        assert result["turn_index"] >= 1
        # Verify turn exists in DB
        turn = db.execute(
            "SELECT * FROM room_turns WHERE room_id = %s ORDER BY turn_index DESC LIMIT 1",
            (room_id,),
        ).fetchone()
        assert turn is not None
        assert turn["status"] == "collecting"

    def test_start_broadcasts_active_snapshot(self, client_with_data):
        data = _create_room(client_with_data)
        room_id = data["room_id"]
        db = client_with_data.app.state.db
        db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, is_ready, status) "
            "VALUES ('ch-snap', %s, 'Alice', 'pt-snap', true, 'joined')",
            (room_id,),
        )
        db.commit()
        res = client_with_data.post(
            f"/api/rooms/{room_id}/start",
            headers={"X-Owner-Token": data["owner_token"]},
        )
        assert res.status_code == 200
        # Verify lobby snapshot event was logged
        events = db.execute(
            "SELECT * FROM events WHERE room_id = %s AND event_type = 's2c_room_lobby_snapshot' "
            "ORDER BY sequence DESC LIMIT 1",
            (room_id,),
        ).fetchone()
        assert events is not None, "Expected lobby snapshot event after start"


def _insert_unpublished_structured_scenario(test_db):
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, raw_text, import_status, publish_status) "
        "VALUES ('sc-unpublished', 'Unpublished', 'legacy text', 'structured', 'draft')"
    )
    test_db.commit()


class TestTurnEndpoints:
    def test_get_current_turn_requires_auth(self, client_with_data):
        data = _create_room(client_with_data)
        res = client_with_data.get(f"/api/rooms/{data['room_id']}/turns/current")
        assert res.status_code == 403

    def test_get_current_turn_with_owner_token(self, client_with_data):
        data = _create_room(client_with_data)
        room_id = data["room_id"]
        db = client_with_data.app.state.db
        # Must start room first to create a turn
        db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, is_ready, status) "
            "VALUES ('ch-ct', %s, 'Alice', 'pt-ct', true, 'joined')",
            (room_id,),
        )
        db.commit()
        client_with_data.post(
            f"/api/rooms/{room_id}/start",
            headers={"X-Owner-Token": data["owner_token"]},
        )
        res = client_with_data.get(
            f"/api/rooms/{room_id}/turns/current",
            headers={"X-Owner-Token": data["owner_token"]},
        )
        assert res.status_code == 200
        result = res.json()
        assert "turn_id" in result
        assert "players" in result
