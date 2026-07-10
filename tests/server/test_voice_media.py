from tests.server.conftest import setup_auth_test_data, create_room


def test_speech_to_text_mock_provider(client, test_db, monkeypatch):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join")
    player_token = joined.json()["player_token"]
    monkeypatch.setenv("STT_PROVIDER", "mock")

    res = client.post(
        "/api/player/speech-to-text",
        headers={"X-Room-Token": player_token},
        files={"audio": ("voice.webm", b"0" * 256, "audio/webm")},
        data={"durationMs": "1200"},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["provider"] == "mock"
    assert data["transcribedText"].startswith("[测试转写]")
