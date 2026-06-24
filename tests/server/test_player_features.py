import json
import pytest
from fastapi.testclient import TestClient
from src.server.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def room_and_player(client):
    res = client.post("/api/rooms", json={})
    room = res.json()
    room_id = room["room_id"]

    res = client.post(f"/api/player/rooms/{room_id}/join")
    player = res.json()
    return room_id, player["player_token"], player["character_id"]


class TestCharacterSheet:
    def test_get_character(self, client, room_and_player):
        _, token, _ = room_and_player
        res = client.get("/api/player/character", headers={"X-Room-Token": token})
        assert res.status_code == 200
        data = res.json()
        assert "name" in data
        assert "skills" in data

    def test_get_character_no_token(self, client):
        res = client.get("/api/player/character")
        assert res.status_code == 401

    def test_get_character_invalid_token(self, client):
        res = client.get("/api/player/character", headers={"X-Room-Token": "bad"})
        assert res.status_code == 403


class TestInventory:
    def test_get_inventory_empty(self, client, room_and_player):
        _, token, _ = room_and_player
        res = client.get("/api/player/inventory", headers={"X-Room-Token": token})
        assert res.status_code == 200
        assert res.json() == []

    def test_get_inventory_with_items(self, client, room_and_player):
        _, token, char_id = room_and_player
        room_id = room_and_player[0]
        conn = app.state.db
        conn.execute(
            "INSERT INTO inventory (id, character_id, room_id, name, description, quantity) VALUES (?, ?, ?, ?, ?, ?)",
            ("item1", char_id, room_id, "手电筒", "一把旧手电筒", 1),
        )
        conn.execute(
            "INSERT INTO inventory (id, character_id, room_id, name, description, quantity, is_secret) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("item2", char_id, room_id, "神秘钥匙", "一把古铜钥匙", 1, 1),
        )
        conn.commit()

        res = client.get("/api/player/inventory", headers={"X-Room-Token": token})
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 2


class TestSkillCheckAPI:
    def test_skill_check(self, client, room_and_player):
        _, token, _ = room_and_player
        res = client.post(
            "/api/player/skill-check",
            json={"skill_name": "侦查", "skill_value": 60, "difficulty": "regular"},
            headers={"X-Room-Token": token},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["skill_name"] == "侦查"
        assert 1 <= data["roll"] <= 100
        assert data["success_level"] in {
            "critical", "extreme", "hard", "regular", "failure", "fumble",
        }

    def test_skill_check_with_bonus_dice(self, client, room_and_player):
        _, token, _ = room_and_player
        res = client.post(
            "/api/player/skill-check",
            json={"skill_name": "闪避", "skill_value": 40, "bonus_dice": 1},
            headers={"X-Room-Token": token},
        )
        assert res.status_code == 200

    def test_skill_check_no_token(self, client):
        res = client.post(
            "/api/player/skill-check",
            json={"skill_name": "侦查", "skill_value": 60},
        )
        assert res.status_code == 401


class TestSync:
    def test_sync_returns_inventory(self, client, room_and_player):
        _, token, char_id = room_and_player
        room_id = room_and_player[0]
        conn = app.state.db
        conn.execute(
            "INSERT INTO inventory (id, character_id, room_id, name, description, quantity) VALUES (?, ?, ?, ?, ?, ?)",
            ("sync-item1", char_id, room_id, "笔记本", "一本旧笔记本", 1),
        )
        conn.commit()

        res = client.get("/api/player/sync", headers={"X-Room-Token": token})
        assert res.status_code == 200
        data = res.json()
        assert "inventory" in data
        assert len(data["inventory"]) == 1
