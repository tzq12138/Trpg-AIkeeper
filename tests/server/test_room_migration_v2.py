import hashlib
import io
import json
import zipfile

from tests.server.conftest import create_room, login, setup_auth_test_data
from src.server.room_migration import RoomMigrationPackage, import_room_package, inspect_room_package


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
        assert manifest["version"] == 2
        assert {entry["path"] for entry in manifest["files"]} == {
            "room.json",
            "characters.json",
            "objectives.json",
            "events.json",
            "fact_reveals.json",
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


def test_imported_room_keeps_its_runtime_package_snapshot(client, test_db):
    room, host_token = _setup_migratable_room(client, test_db)
    scenario_version_id = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["scenario_version_id"]
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, gate_status, "
        "input_checksum, runtime_package, created_by) "
        "VALUES ('migration-runtime-snapshot', %s, 1, 'ready', 'sha', '{}', 'test')",
        (scenario_version_id,),
    )
    test_db.execute(
        "UPDATE rooms SET runtime_package_version_id = 'migration-runtime-snapshot' WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()
    package = _export_package(client, room)

    imported = client.post(
        "/api/imports/confirm",
        data={"confirm": "true"},
        files={"package": ("room.zip", package, "application/zip")},
        headers={"Authorization": f"Bearer {host_token}"},
    )

    assert imported.status_code == 200, imported.text
    copied = test_db.execute(
        "SELECT runtime_package_version_id FROM rooms WHERE room_id = %s",
        (imported.json()["room_id"],),
    ).fetchone()
    assert copied["runtime_package_version_id"] == "migration-runtime-snapshot"


def test_imported_room_discards_an_unavailable_runtime_package_snapshot(client, test_db):
    room, _ = _setup_migratable_room(client, test_db)
    package = inspect_room_package(_export_package(client, room))
    unavailable = RoomMigrationPackage(
        manifest=package.manifest,
        room={**package.room, "runtime_package_version_id": "missing-runtime-package"},
        characters=package.characters,
        objectives=package.objectives,
        events=package.events,
        fact_reveals=package.fact_reveals,
        player_notes=package.player_notes,
    )

    copied_room_id = import_room_package(test_db, unavailable, owner_account_id="acc-host")

    copied = test_db.execute(
        "SELECT runtime_package_version_id FROM rooms WHERE room_id = %s",
        (copied_room_id,),
    ).fetchone()
    assert copied["runtime_package_version_id"] is None


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


def test_admin_global_reset_requires_verified_download_before_deleting_room_data(
    client,
    test_db,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIKEEPER_MIGRATION_BACKUP_DIR", str(tmp_path))
    room, _ = _setup_migratable_room(client, test_db)
    admin_token = login(client, "admin")
    headers = {"Authorization": f"Bearer {admin_token}"}

    preflight = client.get("/api/admin/reset/preflight", headers=headers)
    assert preflight.status_code == 200, preflight.text
    assert preflight.json()["counts"]["rooms"] >= 1
    assert preflight.json()["counts"]["characters"] >= 1

    backup = client.post("/api/admin/reset/backups", headers=headers)
    assert backup.status_code == 201, backup.text
    backup_data = backup.json()
    backup_id = backup_data["backup_id"]
    assert len(backup_data["sha256"]) == 64
    assert backup_data["counts"]["rooms"] >= 1

    blocked = client.post(
        "/api/admin/reset/execute",
        headers=headers,
        json={"backup_id": backup_id, "confirm_download": True},
    )
    assert blocked.status_code == 409

    downloaded = client.get(f"/api/admin/reset/backups/{backup_id}/download", headers=headers)
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["content-type"].startswith("application/zip")
    assert hashlib.sha256(downloaded.content).hexdigest() == backup_data["sha256"]

    invalid_confirmation = client.post(
        "/api/admin/reset/execute",
        headers=headers,
        json={"backup_id": backup_id, "confirm_download": False},
    )
    assert invalid_confirmation.status_code == 400

    verified = client.get(f"/api/admin/reset/backups/{backup_id}/verify", headers=headers)
    assert verified.status_code == 200, verified.text
    assert verified.json()["valid"] is True
    assert verified.json()["counts"]["rooms"] >= 1

    executed = client.post(
        "/api/admin/reset/execute",
        headers=headers,
        json={"backup_id": backup_id, "confirm_download": True},
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["deleted"]["rooms"] >= 1
    assert test_db.execute("SELECT COUNT(*) AS count FROM rooms").fetchone()["count"] == 0
    assert test_db.execute("SELECT COUNT(*) AS count FROM characters").fetchone()["count"] == 0
    assert test_db.execute("SELECT COUNT(*) AS count FROM accounts").fetchone()["count"] >= 3
    assert test_db.execute("SELECT COUNT(*) AS count FROM scenarios WHERE scenario_id = 'sc-test'").fetchone()["count"] == 1
    assert test_db.execute("SELECT COUNT(*) AS count FROM events WHERE room_id = %s", (room["room_id"],)).fetchone()["count"] == 0


def test_room_migration_round_trips_authoritative_fact_reveals(client, test_db):
    from src.server.engine.reveal_ledger import RevealLedger
    from src.server.events.event_log import EventLog

    room, _ = _setup_migratable_room(client, test_db)
    room_row = test_db.execute(
        "SELECT scenario_version_id, state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    test_db.execute(
        "UPDATE characters SET status = 'active' WHERE character_id = 'old-character'"
    )
    test_db.execute(
        "INSERT INTO room_scene_state "
        "(room_id, current_scene, visited_scenes, public_facts, version) "
        "VALUES (%s, 'lobby', '[\"lobby\"]', '[]', 1) "
        "ON CONFLICT (room_id) DO UPDATE SET current_scene = EXCLUDED.current_scene",
        (room["room_id"],),
    )
    test_db.execute(
        "INSERT INTO content_items "
        "(content_item_id, scenario_version_id, item_type, logical_key, title, "
        "visibility, payload, citation, checksum) "
        "VALUES ('migration-fact', %s, 'fact', 'lobby', %s, "
        "'host_only', %s, %s, 'sha-migration-fact')",
        (
            room_row["scenario_version_id"],
            "钟楼的时针已经停下",
            json.dumps({
                "fact_text": "钟楼的时针已经停下",
                "reveal_conditions": {"scene_ids": ["lobby"]},
            }, ensure_ascii=False),
            json.dumps({"page_number": 7}),
        ),
    )
    test_db.commit()
    RevealLedger(test_db).commit_proposals(
        room_id=room["room_id"],
        source_action_id="migration-reveal-action",
        actor_character_id="old-character",
        proposals=[{"content_item_id": "migration-fact", "audience": "party"}],
        state_version=int(room_row["state_version"] or 0),
    )

    package = inspect_room_package(_export_package(client, room))
    copied_room_id = import_room_package(
        test_db,
        package,
        owner_account_id="acc-host",
    )

    copied = test_db.execute(
        "SELECT room_id, fact_id, source_action_id, event_sequence "
        "FROM fact_reveals WHERE room_id = %s",
        (copied_room_id,),
    ).fetchone()
    assert copied["room_id"] == copied_room_id
    assert copied["fact_id"] == "migration-fact"
    assert copied["source_action_id"] == "migration-reveal-action"
    events = EventLog(test_db).get_public_events(copied_room_id)
    assert [event.payload["factText"] for event in events] == [
        "钟楼的时针已经停下"
    ]
