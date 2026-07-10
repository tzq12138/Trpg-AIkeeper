from tests.server.conftest import create_room, setup_auth_test_data


class DummyPipeline:
    async def resolve_queued_room(self, room_id: str):
        return {"room_id": room_id, "resolved": 0, "results": []}


def test_ai_turn_accepts_owner_token_fallback(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client)
    client.app.state.pipeline = DummyPipeline()

    resp = client.post(
        f"/api/rooms/{room['room_id']}/ai-turn",
        headers={"X-Owner-Token": room["owner_token"]},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "No pending actions to process"
