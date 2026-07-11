import hashlib
import io
import json
import zipfile

from tests.server.conftest import create_room, login, setup_auth_test_data


def _setup_migratable_room(client, test_db):
    setup_auth_test_data(test_db)
    host_token = login(client, "testhost")
    room = create_room(client, host_token)
    room_id = room["room_id"]

    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES (%s, %s, %s, %s, %s)",
        ("old-character", room_id, "Alice", "old-player-token", json.dumps({"name": "Alice"})),
    )
    test_db.execute(
        "INSERT INTO objectives (objective_id, room_id, character_id, text, type) "
        "VALUES (%s, %s, %s, %s, %s)",
        ("old-objective", room_id, "old-character", "查明钟楼真相", "personal"),
    )
    test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, %s, %s)",
        (
            room_id,
            "s2c_action_resolved",
            "player",
            json.dumps({
                "roomId": room_id,
                "characterId": "old-character",
                "nested": {"character_id": "old-character"},
                "owner_token": room["owner_token"],
                "player_token": "old-player-token",
            }),
        ),
    )
    test_db.execute(
        "INSERT INTO player_notes (note_id, room_id, character_id, title_ciphertext, "
        "body_ciphertext, visibility) VALUES (%s, %s, %s, %s, %s, %s)",
        (
            "old-note",
            room_id,
            "old-character",
            "encrypted-title",
            "encrypted-body",
            "private",
        ),
    )
    test_db.commit()
    return room, host_token


def _export_package(client, room):
    response = client.get(
        f"/api/exports/rooms/{room['room_id']}/package",
        headers={"X-Owner-Token": room["owner_token"]},
    )
    assert response.status_code == 200, response.text
    return response.content


def test_room_package_export_has_manifest_hashes_and_no_tokens(client, test_db):
    room, host_token = _setup_migratable_room(client, test_db)

    host_export = client.get(
        f"/api/exports/rooms/{room['room_id']}/package",
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert host_export.status_code == 200, host_export.text
    admin_export = client.get(
        f"/api/exports/rooms/{room['room_id']}/package",
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )
    assert admin_export.status_code == 200, admin_export.text

    package = _export_package(client, room)

    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema"] == "aikeeper.room-migration"
        assert manifest["version"] == 1
        assert {entry["path"] for entry in manifest["files"]} == {
            "room.json",
            "characters.json",
            "objectives.json",
            "events.json",
            "player_notes.json",
        }
        for entry in manifest["files"]:
            assert hashlib.sha256(archive.read(entry["path"])).hexdigest() == entry["sha256"]
        event_payload = json.loads(archive.read("events.json"))[0]["payload"]
        assert "owner_token" not in event_payload
        assert "player_token" not in event_payload

    assert room["owner_token"].encode() not in package
    assert b"old-player-token" not in package


def test_preview_does_not_write_and_confirm_creates_remapped_copy(client, test_db):
    room, host_token = _setup_migratable_room(client, test_db)
    package = _export_package(client, room)
    before_rooms = test_db.execute("SELECT COUNT(*) AS count FROM rooms").fetchone()["count"]
    before_characters = test_db.execute("SELECT COUNT(*) AS count FROM characters").fetchone()["count"]

    preview = client.post(
        "/api/imports/preview",
        files={"package": ("room.zip", package, "application/zip")},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["valid"] is True
    assert test_db.execute("SELECT COUNT(*) AS count FROM rooms").fetchone()["count"] == before_rooms
    assert test_db.execute("SELECT COUNT(*) AS count FROM characters").fetchone()["count"] == before_characters

    missing_confirmation = client.post(
        "/api/imports/confirm",
        data={"confirm": "false"},
        files={"package": ("room.zip", package, "application/zip")},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert missing_confirmation.status_code == 400

    confirmed = client.post(
        "/api/imports/confirm",
        data={"confirm": "true"},
        files={"package": ("room.zip", package, "application/zip")},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert confirmed.status_code == 200, confirmed.text
    new_room_id = confirmed.json()["room_id"]
    assert new_room_id != room["room_id"]

    copied_character = test_db.execute(
        "SELECT character_id, player_token FROM characters WHERE room_id = %s",
        (new_room_id,),
    ).fetchone()
    assert copied_character["character_id"] != "old-character"
    assert copied_character["player_token"] != "old-player-token"
    copied_objective = test_db.execute(
        "SELECT character_id FROM objectives WHERE room_id = %s", (new_room_id,)
    ).fetchone()
    assert copied_objective["character_id"] == copied_character["character_id"]
    copied_event = test_db.execute(
        "SELECT payload FROM events WHERE room_id = %s", (new_room_id,)
    ).fetchone()["payload"]
    assert copied_event["roomId"] == new_room_id
    assert copied_event["characterId"] == copied_character["character_id"]
    assert copied_event["nested"]["character_id"] == copied_character["character_id"]
    copied_note = test_db.execute(
        "SELECT character_id, title_ciphertext, body_ciphertext FROM player_notes WHERE room_id = %s",
        (new_room_id,),
    ).fetchone()
    assert copied_note["character_id"] == copied_character["character_id"]
    assert copied_note["title_ciphertext"] == "encrypted-title"
    assert copied_note["body_ciphertext"] == "encrypted-body"


def test_preview_rejects_hash_tampering_and_requires_host_or_admin(client, test_db):
    room, host_token = _setup_migratable_room(client, test_db)
    package = _export_package(client, room)
    with zipfile.ZipFile(io.BytesIO(package)) as original:
        tampered_buffer = io.BytesIO()
        with zipfile.ZipFile(tampered_buffer, "w", zipfile.ZIP_DEFLATED) as tampered:
            for item in original.infolist():
                data = original.read(item.filename)
                if item.filename == "characters.json":
                    data = b"[]"
                tampered.writestr(item.filename, data)
    tampered = tampered_buffer.getvalue()

    unauthenticated = client.post(
        "/api/imports/preview",
        files={"package": ("room.zip", package, "application/zip")},
    )
    assert unauthenticated.status_code == 401

    player_token = login(client, "testplayer")
    forbidden = client.post(
        "/api/imports/preview",
        files={"package": ("room.zip", package, "application/zip")},
        headers={"Authorization": f"Bearer {player_token}"},
    )
    assert forbidden.status_code == 403

    before = test_db.execute("SELECT COUNT(*) AS count FROM rooms").fetchone()["count"]
    rejected = client.post(
        "/api/imports/preview",
        files={"package": ("room.zip", tampered, "application/zip")},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert rejected.status_code == 422
    assert test_db.execute("SELECT COUNT(*) AS count FROM rooms").fetchone()["count"] == before
