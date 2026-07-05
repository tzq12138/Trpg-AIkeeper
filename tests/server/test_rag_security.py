"""Security tests for RAG search and indexing endpoints."""

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
        ("acc-host", "raghost", "host"),
        ("acc-p1", "ragp1", "player"),
    ]:
        test_db.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (account_id) DO UPDATE SET role = %s",
            (aid, uname, _hash_password("test123"), uname, role, role),
        )
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, raw_text, import_status) "
        "VALUES ('rag-sc1', 'RAG Scenario', 'text', 'structured')"
    )
    test_db.execute(
        "INSERT INTO rooms (room_id, scenario_id, owner_token, owner_account_id, status) "
        "VALUES ('rag-room', 'rag-sc1', 'owntok', 'acc-host', 'lobby')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, account_id, status) "
        "VALUES ('rag-ch1', 'rag-room', 'Alice', 'ptok-rag', 'acc-p1', 'active')"
    )
    test_db.commit()
    return c


class TestRAGIndexAuth:
    def test_index_scenario_no_auth_returns_401(self, client_with_data):
        res = client_with_data.post("/api/rag/index", json={
            "scenario_id": "rag-sc1", "room_id": "rag-room",
        })
        assert res.status_code == 401

    def test_index_scenario_wrong_player_returns_403(self, client_with_data):
        # Player is in rag-room — let player try to index (write op)
        token = _login(client_with_data, "ragp1", "test123")
        res = client_with_data.post(
            "/api/rag/index",
            json={"scenario_id": "rag-sc1", "room_id": "rag-room"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # player cannot write/index — 403
        assert res.status_code == 403


class TestRAGSearchAuth:
    def test_search_no_auth_returns_401(self, client_with_data):
        res = client_with_data.post("/api/rag/search", json={
            "query": "test", "room_id": "rag-room",
        })
        assert res.status_code == 401

    def test_search_room_player_can_search(self, client_with_data):
        # Mock rag store on app state
        class MockRag:
            def search(self, *a, **kw):
                return []
        app.state.rag = MockRag()
        token = _login(client_with_data, "ragp1", "test123")
        res = client_with_data.post(
            "/api/rag/search",
            json={"query": "线索", "room_id": "rag-room"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Player in room can search
        assert res.status_code == 200

    def test_search_wrong_room_returns_403(self, client_with_data, test_db):
        # Create another room that the player is NOT in
        test_db.execute(
            "INSERT INTO rooms (room_id, scenario_id, owner_token, owner_account_id, status) "
            "VALUES ('rag-room2', 'rag-sc1', 'tok2', 'acc-admin', 'lobby')"
        )
        test_db.commit()
        token = _login(client_with_data, "ragp1", "test123")
        res = client_with_data.post(
            "/api/rag/search",
            json={"query": "线索", "room_id": "rag-room2"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403


class TestRuleDocs:
    def test_rule_docs_no_auth_returns_401(self, client_with_data):
        res = client_with_data.get("/api/rag/rule-docs")
        assert res.status_code == 401

    def test_rule_docs_with_auth_returns_ok(self, client_with_data):
        token = _login(client_with_data, "admin", "test123")
        res = client_with_data.get(
            "/api/rag/rule-docs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200


class TestRAGHostAdmin:
    def test_index_as_host_succeeds(self, client_with_data):
        """Host (room owner) can index their own room."""
        class MockRagFull:
            def index_scenario(self, *a, **kw): return {"indexed": 0}
        app.state.rag = MockRagFull()
        token = _login(client_with_data, "raghost", "test123")
        res = client_with_data.post(
            "/api/rag/index",
            json={"scenario_id": "rag-sc1", "room_id": "rag-room"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200

    def test_index_as_admin_succeeds(self, client_with_data):
        """Admin can index any room."""
        class MockRagFull:
            def index_scenario(self, *a, **kw): return {"indexed": 0}
        app.state.rag = MockRagFull()
        token = _login(client_with_data, "admin", "test123")
        res = client_with_data.post(
            "/api/rag/index",
            json={"scenario_id": "rag-sc1", "room_id": "rag-room"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200

    def test_search_as_host_succeeds(self, client_with_data):
        """Host (room owner) can search their room."""
        class MockRagSearch:
            def search(self, *a, **kw): return []
        app.state.rag = MockRagSearch()
        token = _login(client_with_data, "raghost", "test123")
        res = client_with_data.post(
            "/api/rag/search",
            json={"query": "test", "room_id": "rag-room"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200


def _login(client, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={
        "username": username, "password": password,
    })
    assert res.status_code == 200, f"Login failed: {res.text}"
    return res.json()["token"]
