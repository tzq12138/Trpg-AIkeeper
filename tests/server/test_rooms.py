def test_create_room(client):
    resp = client.post("/api/rooms", json={"scenario_id": "sc-1", "spoiler_level": "standard"})
    assert resp.status_code == 200
    data = resp.json()
    assert "room_id" in data
    assert "owner_token" in data
    assert data["status"] == "lobby"


def test_get_room(client):
    resp = client.post("/api/rooms", json={})
    room_id = resp.json()["room_id"]
    resp = client.get(f"/api/rooms/{room_id}")
    assert resp.status_code == 200
    assert resp.json()["room_id"] == room_id


def test_get_room_not_found(client):
    resp = client.get("/api/rooms/nonexistent")
    assert resp.status_code == 404


def test_start_room(client):
    resp = client.post("/api/rooms", json={})
    data = resp.json()
    resp = client.post(
        f"/api/rooms/{data['room_id']}/start",
        headers={"X-Owner-Token": data["owner_token"]},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


def test_start_room_wrong_owner(client):
    resp = client.post("/api/rooms", json={})
    data = resp.json()
    resp = client.post(
        f"/api/rooms/{data['room_id']}/start",
        headers={"X-Owner-Token": "wrong-token"},
    )
    assert resp.status_code == 403
