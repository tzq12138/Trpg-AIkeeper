import json
import pytest
from fastapi.testclient import TestClient
from src.server.main import app
from tests.server.conftest import setup_auth_test_data, create_room


@pytest.fixture
def room_and_player(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client)
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
            "INSERT INTO inventory (id, character_id, room_id, name, description, quantity) VALUES (%s, %s, %s, %s, %s, %s)",
            ("item1", char_id, room_id, "手电筒", "一把旧手电筒", 1),
        )
        conn.execute(
            "INSERT INTO inventory (id, character_id, room_id, name, description, quantity, is_secret) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            ("item2", char_id, room_id, "神秘钥匙", "一把古铜钥匙", 1, 1),
        )
        conn.commit()

        res = client.get("/api/player/inventory", headers={"X-Room-Token": token})
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 2


class TestInventoryTransfers:
    def _two_players_with_item(self, client, test_db):
        setup_auth_test_data(test_db)
        room = create_room(client)
        room_id = room["room_id"]
        sender = client.post(f"/api/player/rooms/{room_id}/join").json()
        recipient = client.post(f"/api/player/rooms/{room_id}/join").json()
        test_db.execute(
            "INSERT INTO inventory (id, character_id, room_id, name, description, quantity, is_secret, source) "
            "VALUES ('transfer-item', %s, %s, '急救包', '带有私人标记的急救包', 2, TRUE, 'test')",
            (sender["character_id"], room_id),
        )
        test_db.commit()
        return room_id, sender, recipient

    def test_transfer_keeps_item_with_sender_until_recipient_accepts(self, client, test_db):
        room_id, sender, recipient = self._two_players_with_item(client, test_db)

        response = client.post(
            "/api/player/inventory/transfer-item/transfers",
            json={"toCharacterId": recipient["character_id"], "quantity": 1},
            headers={"X-Room-Token": sender["player_token"]},
        )

        assert response.status_code == 201
        transfer = response.json()
        assert transfer["status"] == "pending"
        assert transfer["itemName"] == "急救包"
        source_item = test_db.execute(
            "SELECT character_id, quantity FROM inventory WHERE id = 'transfer-item'"
        ).fetchone()
        assert source_item == {"character_id": sender["character_id"], "quantity": 2}
        incoming = client.get(
            "/api/player/inventory-transfers",
            headers={"X-Room-Token": recipient["player_token"]},
        )
        assert incoming.status_code == 200
        assert incoming.json()["incoming"][0]["transferId"] == transfer["transferId"]
        sender_name = test_db.execute(
            "SELECT player_name FROM characters WHERE character_id = %s",
            (sender["character_id"],),
        ).fetchone()["player_name"]
        assert incoming.json()["incoming"][0]["fromPlayerName"] == sender_name
        assert "description" not in incoming.json()["incoming"][0]

    def test_accepting_transfer_moves_requested_quantity_atomically(self, client, test_db):
        room_id, sender, recipient = self._two_players_with_item(client, test_db)
        requested = client.post(
            "/api/player/inventory/transfer-item/transfers",
            json={"toCharacterId": recipient["character_id"], "quantity": 1},
            headers={"X-Room-Token": sender["player_token"]},
        ).json()

        accepted = client.post(
            f"/api/player/inventory-transfers/{requested['transferId']}/accept",
            headers={"X-Room-Token": recipient["player_token"]},
        )

        assert accepted.status_code == 200
        assert accepted.json()["status"] == "completed"
        items = test_db.execute(
            "SELECT character_id, quantity FROM inventory WHERE room_id = %s ORDER BY character_id, id",
            (room_id,),
        ).fetchall()
        assert sorted((item["character_id"], item["quantity"]) for item in items) == sorted([
            (recipient["character_id"], 1),
            (sender["character_id"], 1),
        ])
        transfer = test_db.execute(
            "SELECT status FROM inventory_transfer_requests WHERE transfer_id = %s",
            (requested["transferId"],),
        ).fetchone()
        assert transfer["status"] == "completed"

    def test_accepting_an_unavailable_transfer_marks_it_unavailable(self, client, test_db):
        _, sender, recipient = self._two_players_with_item(client, test_db)
        requested = client.post(
            "/api/player/inventory/transfer-item/transfers",
            json={"toCharacterId": recipient["character_id"], "quantity": 1},
            headers={"X-Room-Token": sender["player_token"]},
        ).json()
        test_db.execute("DELETE FROM inventory WHERE id = 'transfer-item'")
        test_db.commit()

        unavailable = client.post(
            f"/api/player/inventory-transfers/{requested['transferId']}/accept",
            headers={"X-Room-Token": recipient["player_token"]},
        )

        assert unavailable.status_code == 409
        transfer = test_db.execute(
            "SELECT status FROM inventory_transfer_requests WHERE transfer_id = %s",
            (requested["transferId"],),
        ).fetchone()
        assert transfer["status"] == "unavailable"


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
            "INSERT INTO inventory (id, character_id, room_id, name, description, quantity) VALUES (%s, %s, %s, %s, %s, %s)",
            ("sync-item1", char_id, room_id, "笔记本", "一本旧笔记本", 1),
        )
        conn.commit()

        res = client.get("/api/player/sync", headers={"X-Room-Token": token})
        assert res.status_code == 200
        data = res.json()
        assert "inventory" in data
        assert len(data["inventory"]) == 1
