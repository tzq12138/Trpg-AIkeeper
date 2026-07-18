"""Admin endpoint auth tests: accounts, role management."""

import pytest
from fastapi.testclient import TestClient
from src.server.main import app
from src.server.router_auth import _hash_password
from tests.server.conftest import create_scenario


@pytest.fixture
def client_with_data(test_db):
    from src.server.engine.engine import Engine
    c = TestClient(app)
    app.state.db = test_db
    app.state.engine = Engine(test_db)

    for aid, uname, role in [
        ("acc-admin", "admin", "admin"),
        ("acc-host", "hostuser", "host"),
        ("acc-player", "player1", "player"),
    ]:
        test_db.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (username) DO UPDATE "
            "SET role = %s, account_id = EXCLUDED.account_id",
            (aid, uname, _hash_password("test123"), uname, role, role),
        )
    test_db.commit()
    return c


def _login(client, username: str, password: str = "test123") -> str:
    res = client.post("/api/auth/login", json={
        "username": username, "password": password,
    })
    assert res.status_code == 200, f"Login failed: {res.text}"
    return res.json()["token"]


class TestAdminAccounts:
    def test_acceptance_center_requires_admin_and_returns_safe_fixtures(self, client_with_data):
        assert client_with_data.get("/api/admin/acceptance").status_code == 401

        player_token = _login(client_with_data, "player1")
        denied = client_with_data.get(
            "/api/admin/acceptance",
            headers={"Authorization": f"Bearer {player_token}"},
        )
        assert denied.status_code == 403

        admin_token = _login(client_with_data, "admin")
        accepted = client_with_data.get(
            "/api/admin/acceptance",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert accepted.status_code == 200
        data = accepted.json()
        assert data["retention_days"] == 90
        assert data["fixtures"]
        assert all(set(fixture) == {"label", "description", "href"} for fixture in data["fixtures"])

    def test_list_accounts_requires_admin(self, client_with_data):
        res = client_with_data.get("/api/admin/accounts")
        assert res.status_code == 401

    def test_list_accounts_player_rejected(self, client_with_data):
        token = _login(client_with_data, "player1")
        res = client_with_data.get(
            "/api/admin/accounts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403

    def test_list_accounts_as_admin(self, client_with_data):
        token = _login(client_with_data, "admin")
        res = client_with_data.get(
            "/api/admin/accounts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) >= 3
        # Must not expose password_hash
        for acct in data:
            assert "password_hash" not in acct

    def test_promote_player_to_host(self, client_with_data, test_db):
        token = _login(client_with_data, "admin")
        res = client_with_data.patch(
            "/api/admin/accounts/acc-player",
            json={"role": "host"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "updated"
        # Verify role changed in DB
        acc = test_db.execute(
            "SELECT role FROM accounts WHERE account_id = 'acc-player'"
        ).fetchone()
        assert acc["role"] == "host"

    def test_promote_invalid_role_rejected(self, client_with_data):
        token = _login(client_with_data, "admin")
        res = client_with_data.patch(
            "/api/admin/accounts/acc-player",
            json={"role": "superadmin"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 400

    def test_reserved_admin_cannot_be_demoted(self, client_with_data, test_db):
        token = _login(client_with_data, "admin")
        res = client_with_data.patch(
            "/api/admin/accounts/acc-admin",
            json={"role": "player"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 409
        account = test_db.execute(
            "SELECT role FROM accounts WHERE account_id = 'acc-admin'"
        ).fetchone()
        assert account["role"] == "admin"

    def test_player_cannot_access_admin(self, client_with_data):
        token = _login(client_with_data, "player1")
        res = client_with_data.patch(
            "/api/admin/accounts/acc-player",
            json={"role": "host"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403


class TestAdminCharacterDetail:
    def test_char_detail_excludes_player_token(self, client_with_data, test_db):
        """Admin character detail must not leak player_token."""
        token = _login(client_with_data, "admin")
        # Create a room and character for testing
        create_scenario(test_db, "sc-adm", "Admin Test")
        host_token = _login(client_with_data, "hostuser")
        res = client_with_data.post(
            "/api/rooms",
            json={"scenario_id": "sc-adm"},
            headers={"Authorization": f"Bearer {host_token}"},
        )
        room_id = res.json()["room_id"]
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
            "VALUES ('ch-adm-det', %s, 'TestPlayer', 'secret-pt-adm', 'joined')",
            (room_id,),
        )
        test_db.commit()

        res = client_with_data.get(
            f"/api/admin/characters?room_id={room_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        import json
        body = json.dumps(res.json())
        assert "secret-pt-adm" not in body
        assert "player_token" not in body


class TestAdminRoomScenarioVersion:
    def test_switch_scenario_binds_published_version(self, client_with_data, test_db):
        token = _login(client_with_data, "admin")
        test_db.execute(
            "INSERT INTO scenarios (scenario_id, title, import_status, publish_status) "
            "VALUES ('sc-versioned', 'Versioned', 'draft_review', 'published')"
        )
        test_db.execute(
            "INSERT INTO scenario_versions ("
            "scenario_version_id, scenario_id, version_number, status, knowledge_graph, "
            "quality_report, prep_package, created_by"
            ") VALUES ('sv-published', 'sc-versioned', 1, 'published', '{}', '{}', '{}', 'acc-admin')"
        )
        test_db.execute(
            "UPDATE scenarios SET published_version_id = 'sv-published' "
            "WHERE scenario_id = 'sc-versioned'"
        )
        test_db.execute(
            "INSERT INTO rooms (room_id, owner_token, owner_account_id) "
            "VALUES ('room-admin-switch', 'owner-admin-switch', 'acc-admin')"
        )
        test_db.commit()

        response = client_with_data.patch(
            "/api/admin/rooms/room-admin-switch",
            json={"scenario_id": "sc-versioned"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200, response.text
        room = test_db.execute(
            "SELECT scenario_id, scenario_version_id FROM rooms "
            "WHERE room_id = 'room-admin-switch'"
        ).fetchone()
        assert room["scenario_id"] == "sc-versioned"
        assert room["scenario_version_id"] == "sv-published"

    def test_switch_scenario_rejects_unpublished_draft(self, client_with_data, test_db):
        token = _login(client_with_data, "admin")
        test_db.execute(
            "INSERT INTO scenarios (scenario_id, title, import_status, publish_status) "
            "VALUES ('sc-draft-only', 'Draft', 'structured', 'draft')"
        )
        test_db.execute(
            "INSERT INTO rooms (room_id, owner_token, owner_account_id) "
            "VALUES ('room-admin-draft', 'owner-admin-draft', 'acc-admin')"
        )
        test_db.commit()

        response = client_with_data.patch(
            "/api/admin/rooms/room-admin-draft",
            json={"scenario_id": "sc-draft-only"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 409
