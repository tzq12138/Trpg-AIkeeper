"""Auth endpoint tests: register, login, /me, /me/characters."""

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
    return c


def _login(client, username: str, password: str = "test123") -> str:
    res = client.post("/api/auth/login", json={
        "username": username, "password": password,
    })
    assert res.status_code == 200, f"Login failed: {res.text}"
    return res.json()["token"]


class TestRegister:
    def test_register_creates_account(self, client_with_data, test_db):
        res = client_with_data.post("/api/auth/register", json={
            "username": "newuser", "password": "test123", "display_name": "New User",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["username"] == "newuser"
        assert data["display_name"] == "New User"
        assert "token" in data
        assert "account_id" in data

    def test_duplicate_username_returns_409(self, client_with_data):
        # Register first
        client_with_data.post("/api/auth/register", json={
            "username": "dupuser", "password": "test123",
        })
        # Register same username again
        res = client_with_data.post("/api/auth/register", json={
            "username": "dupuser", "password": "test456",
        })
        assert res.status_code == 409


class TestFirstAccountAdmin:
    def test_first_account_is_admin(self, client_with_data, test_db):
        """First account in an empty database gets admin role."""
        # Ensure no accounts exist
        test_db.execute("DELETE FROM accounts")
        test_db.commit()
        res = client_with_data.post("/api/auth/register", json={
            "username": "firstadmin", "password": "test123",
        })
        assert res.status_code == 200
        assert res.json()["role"] == "admin"

    def test_subsequent_account_is_player(self, client_with_data, test_db):
        """After first admin exists, new accounts default to player."""
        # Ensure exactly one admin account exists first
        test_db.execute("DELETE FROM accounts")
        test_db.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES ('acc-existing', 'existingadmin', %s, 'Admin', 'admin')",
            (_hash_password("test123"),),
        )
        test_db.commit()
        res = client_with_data.post("/api/auth/register", json={
            "username": "normalplayer", "password": "test123",
        })
        assert res.status_code == 200
        assert res.json()["role"] == "player"


class TestAuthMe:
    def test_me_returns_account(self, client_with_data, test_db):
        # Register an admin first so "metest" defaults to player
        test_db.execute("DELETE FROM accounts")
        test_db.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES ('acc-first', 'first', %s, 'First', 'admin')",
            (_hash_password("test123"),),
        )
        test_db.commit()
        # Register second account
        client_with_data.post("/api/auth/register", json={
            "username": "metest", "password": "test123", "display_name": "Me Test",
        })
        token = _login(client_with_data, "metest")

        res = client_with_data.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["username"] == "metest"
        assert data["display_name"] == "Me Test"
        assert data["role"] == "player"

    def test_me_no_token_returns_401(self, client_with_data):
        res = client_with_data.get("/api/auth/me")
        assert res.status_code == 401

    def test_me_invalid_token_returns_401(self, client_with_data):
        res = client_with_data.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert res.status_code == 401


class TestAuthMeCharacters:
    def test_me_characters_lists_my_chars(self, client_with_data, test_db):
        """GET /api/auth/me/characters should list characters owned by the account."""
        from tests.server.conftest import create_account, create_scenario, create_room, login

        # Create account and login
        create_account(test_db, "acc-mechar", "mecharuser", "host")
        create_scenario(test_db, "sc-mechar", "Me Char Scenario")
        test_db.commit()

        token = login(client_with_data, "mecharuser")
        room = create_room(client_with_data, token, "sc-mechar")

        # Join with this account
        client_with_data.post(
            f"/api/player/rooms/{room['room_id']}/join-with-character",
            data={
                "player_name": "MeCharPlayer",
                "character_data": '{"name":"TestChar","occupation":"Doctor","age":30,"attributes":{"luck":50},"skills":{},"derived_stats":{"hp":10,"san":50,"mp":10}}',
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        res = client_with_data.get(
            "/api/auth/me/characters",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_me_characters_no_token_returns_401(self, client_with_data):
        res = client_with_data.get("/api/auth/me/characters")
        assert res.status_code == 401
