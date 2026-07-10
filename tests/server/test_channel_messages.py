"""Team message endpoint tests."""

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
        ("acc-host", "chost", "host"),
    ]:
        test_db.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (username) DO UPDATE "
            "SET role = %s, account_id = EXCLUDED.account_id",
            (aid, uname, _hash_password("test123"), uname, role, role),
        )
    create_scenario(test_db, "sc-chmsg", "Chat Test")
    test_db.commit()
    return c


def _setup_player(client_with_data, test_db):
    """Create room, join as player, return (player_token, room_id)."""
    from tests.server.conftest import create_room, login
    token = login(client_with_data, "chost")
    room = create_room(client_with_data, token, "sc-chmsg")
    resp = client_with_data.post(f"/api/player/rooms/{room['room_id']}/join")
    assert resp.status_code == 200
    return resp.json()["player_token"], room["room_id"]


class TestTeamMessageSend:
    def test_send_team_message_success(self, client_with_data, test_db):
        ptok, _ = _setup_player(client_with_data, test_db)
        res = client_with_data.post(
            "/api/player/team-message",
            json={"text": "Hello team!", "source": "text"},
            headers={"X-Room-Token": ptok},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "sent"
        assert "messageId" in data

    def test_send_team_message_empty_text_400(self, client_with_data, test_db):
        ptok, _ = _setup_player(client_with_data, test_db)
        res = client_with_data.post(
            "/api/player/team-message",
            json={"text": "   ", "source": "text"},
            headers={"X-Room-Token": ptok},
        )
        assert res.status_code == 400

    def test_send_team_message_too_long_400(self, client_with_data, test_db):
        ptok, _ = _setup_player(client_with_data, test_db)
        res = client_with_data.post(
            "/api/player/team-message",
            json={"text": "x" * 2001, "source": "text"},
            headers={"X-Room-Token": ptok},
        )
        assert res.status_code == 400

    def test_send_team_message_invalid_source_400(self, client_with_data, test_db):
        ptok, _ = _setup_player(client_with_data, test_db)
        res = client_with_data.post(
            "/api/player/team-message",
            json={"text": "Hi", "source": "invalid"},
            headers={"X-Room-Token": ptok},
        )
        assert res.status_code == 400

    def test_send_team_message_no_token_401(self, client_with_data):
        res = client_with_data.post(
            "/api/player/team-message",
            json={"text": "Hi", "source": "text"},
        )
        assert res.status_code == 401

    def test_team_message_writes_event_to_db(self, client_with_data, test_db):
        ptok, room_id = _setup_player(client_with_data, test_db)
        res = client_with_data.post(
            "/api/player/team-message",
            json={"text": "Event log test", "source": "text"},
            headers={"X-Room-Token": ptok},
        )
        assert res.status_code == 200
        events = test_db.execute(
            "SELECT * FROM events WHERE room_id = %s AND event_type = 's2c_team_message'",
            (room_id,),
        ).fetchall()
        assert len(events) >= 1
        # Verify audience is party
        assert events[0]["audience"] == "party"
