"""Security tests for room, scenario, and RAG endpoints."""

import json
import pytest
from fastapi.testclient import TestClient
from src.server.main import app
from src.server.router_auth import _hash_password


@pytest.fixture
def client_with_data(test_db):
    """Set up accounts, scenario, and room for security tests."""
    from src.server.engine.engine import Engine
    c = TestClient(app)
    app.state.db = test_db
    app.state.engine = Engine(test_db)

    # Create accounts
    for aid, uname, role in [
        ("acc-admin", "admin", "admin"),
        ("acc-host", "hostuser", "host"),
        ("acc-player1", "player1", "player"),
        ("acc-player2", "player2", "player"),
    ]:
        test_db.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (account_id) DO UPDATE SET role = %s",
            (aid, uname, _hash_password("test123"), uname, role, role),
        )
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, raw_text, import_status) "
        "VALUES ('sc-test', 'Test Scenario', 'Some text', 'structured')"
    )
    test_db.commit()
    return c


class TestRoomDTODesensitized:
    def test_room_info_excludes_owner_token(self, client_with_data, test_db):
        """GET /api/rooms/{id} must NOT return owner_token."""
        test_db.execute(
            "INSERT INTO rooms (room_id, scenario_id, owner_token, owner_account_id, status) "
            "VALUES ('r-sec1', 'sc-test', 'secret-token', 'acc-host', 'lobby')"
        )
        test_db.commit()
        res = client_with_data.get("/api/rooms/r-sec1")
        assert res.status_code == 200
        data = res.json()
        assert "owner_token" not in data
        assert "owner_account_id" not in data
        assert data["room_id"] == "r-sec1"
        assert data["scenario_id"] == "sc-test"

    def test_room_info_excludes_player_tokens(self, client_with_data, test_db):
        """GET /api/rooms/{id} must NOT leak player_token in players array."""
        test_db.execute(
            "INSERT INTO rooms (room_id, scenario_id, owner_token, status) "
            "VALUES ('r-sec3', 'sc-test', 'tok', 'lobby')"
        )
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
            "VALUES ('ch-sec3', 'r-sec3', 'Bob', 'secret-player-tok', 'joined')"
        )
        test_db.commit()
        res = client_with_data.get("/api/rooms/r-sec3")
        assert res.status_code == 200
        body = json.dumps(res.json())
        assert "secret-player-tok" not in body
        # Verify players array exists and has expected fields
        players = res.json().get("players", [])
        assert len(players) == 1
        assert players[0]["character_id"] == "ch-sec3"
        assert players[0]["player_name"] == "Bob"
        assert "player_token" not in players[0]

    def test_room_info_includes_player_count(self, client_with_data, test_db):
        test_db.execute(
            "INSERT INTO rooms (room_id, scenario_id, owner_token, status) "
            "VALUES ('r-sec2', 'sc-test', 'tok', 'lobby')"
        )
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
            "VALUES ('ch1', 'r-sec2', 'Alice', 'pt1', 'active'), "
            "('ch2', 'r-sec2', 'Bob', 'pt2', 'joined')"
        )
        test_db.commit()
        res = client_with_data.get("/api/rooms/r-sec2")
        assert res.status_code == 200
        assert res.json()["player_count"] == 2


class TestScenariosAvailableAuth:
    def test_list_available_no_auth_returns_401(self, client_with_data):
        res = client_with_data.get("/api/scenarios/available")
        assert res.status_code == 401

    def test_list_available_player_returns_403(self, client_with_data):
        token = _login(client_with_data, "player1", "test123")
        res = client_with_data.get(
            "/api/scenarios/available",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403

    def test_list_available_host_succeeds(self, client_with_data):
        token = _login(client_with_data, "hostuser", "test123")
        res = client_with_data.get(
            "/api/scenarios/available",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["scenario_id"] == "sc-test"
        assert data[0]["title"] == "Test Scenario"

    def test_list_available_admin_succeeds(self, client_with_data):
        token = _login(client_with_data, "admin", "test123")
        res = client_with_data.get(
            "/api/scenarios/available",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)


class TestScenarioImportAuth:
    def test_import_pdf_no_auth_returns_401(self, client_with_data):
        res = client_with_data.post(
            "/api/scenarios/import-pdf",
            files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert res.status_code == 401

    def test_import_pdf_player_returns_403(self, client_with_data):
        token = _login(client_with_data, "player1", "test123")
        res = client_with_data.post(
            "/api/scenarios/import-pdf",
            files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403

    def test_create_room_from_scenario_no_auth_returns_401(self, client_with_data):
        res = client_with_data.post("/api/scenarios/sc-test/create-room")
        assert res.status_code == 401


class TestCreateRoomAuth:
    def test_create_room_no_auth_returns_401(self, client_with_data):
        res = client_with_data.post("/api/rooms", json={"scenario_id": "sc-test"})
        assert res.status_code == 401

    def test_create_room_player_returns_403(self, client_with_data):
        token = _login(client_with_data, "player1", "test123")
        res = client_with_data.post(
            "/api/rooms",
            json={"scenario_id": "sc-test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403

    def test_create_room_host_succeeds(self, client_with_data, test_db):
        token = _login(client_with_data, "hostuser", "test123")
        res = client_with_data.post(
            "/api/rooms",
            json={"scenario_id": "sc-test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["room_id"]
        assert data["owner_token"]
        assert data["owner_account_id"] == "acc-host"


class TestActiveJoinPendingApproval:
    def test_active_join_creates_pending_approval(self, client_with_data, test_db):
        """Joining an active room should set status to pending_approval."""
        # Create room and start it
        token = _login(client_with_data, "hostuser", "test123")
        room = _create_room(client_with_data, token)
        room_id = room["room_id"]
        owner_token = room["owner_token"]

        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, is_ready, status) "
            "VALUES ('ch-act', %s, 'HostPlayer', 'pt-act', true, 'joined')",
            (room_id,),
        )
        test_db.commit()
        client_with_data.post(
            f"/api/rooms/{room_id}/start",
            headers={"X-Owner-Token": owner_token},
        )

        # Now join as a new player while room is active
        resp = client_with_data.post(
            f"/api/player/rooms/{room_id}/join",
        )
        assert resp.status_code == 200
        data = resp.json()
        character_id = data["character_id"]
        assert data["status"] == "pending_approval"

        char = test_db.execute(
            "SELECT status FROM characters WHERE character_id = %s",
            (character_id,),
        ).fetchone()
        assert char["status"] == "pending_approval"


class TestIdentityRestoreSecurity:
    def test_account_cannot_restore_others_character(self, client_with_data, test_db):
        """Account A should not be able to restore Account B's character session."""
        test_db.execute(
            "INSERT INTO rooms (room_id, scenario_id, owner_token, owner_account_id, status) "
            "VALUES ('r-restore', 'sc-test', 'tok-restore', 'acc-host', 'active')"
        )
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, account_id, status) "
            "VALUES ('ch-restore', 'r-restore', 'HostChar', 'pt-restore', 'acc-host', 'joined')"
        )
        test_db.commit()

        # Login as different account (player1) and try to restore host's character
        token = _login(client_with_data, "player1", "test123")
        resp = client_with_data.post(
            "/api/player/characters/ch-restore/restore-session",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


class TestGetMineRoomsAuth:
    def test_get_mine_rooms_no_auth_returns_401(self, client_with_data):
        res = client_with_data.get("/api/rooms/mine")
        assert res.status_code == 401

    def test_get_mine_rooms_player_returns_403(self, client_with_data):
        token = _login(client_with_data, "player1", "test123")
        res = client_with_data.get(
            "/api/rooms/mine",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403

    def test_get_mine_rooms_host_succeeds(self, client_with_data):
        token = _login(client_with_data, "hostuser", "test123")
        res = client_with_data.get(
            "/api/rooms/mine",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)


def _login(client, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={
        "username": username, "password": password,
    })
    assert res.status_code == 200, f"Login failed: {res.text}"
    return res.json()["token"]


def _create_room(client, token: str = None, scenario_id: str = "sc-test") -> dict:
    if token is None:
        token = _login(client, "hostuser", "test123")
    res = client.post(
        "/api/rooms",
        json={"scenario_id": scenario_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, f"Create room failed: {res.text}"
    return res.json()
