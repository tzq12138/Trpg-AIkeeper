import json
import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from src.server.main import app
from src.server.router_auth import _hash_password
from src.server.v2_cutover import (
    CUTOVER_CONFIRMATION,
    V2CutoverError,
    V2CutoverService,
)


def _seed_room(conn, room_id: str, version: str) -> None:
    conn.execute(
        "INSERT INTO rooms (room_id, owner_token, status, player_experience_version) "
        "VALUES (%s, %s, 'active', %s)",
        (room_id, f"owner-{room_id}", version),
    )
    conn.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES (%s, %s, %s, %s)",
        (f"char-{room_id}", room_id, "调查员", f"player-{room_id}"),
    )
    conn.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) "
        "VALUES (%s, 's2c_public_observation', 'party', %s)",
        (room_id, json.dumps({"text": "现场仍有余温"}, ensure_ascii=False)),
    )


def test_cutover_requires_exact_confirmation_and_keeps_rooms(test_db, tmp_path):
    _seed_room(test_db, "v2-room", "v2")
    service = V2CutoverService(test_db, tmp_path)

    with pytest.raises(V2CutoverError, match="确认短语"):
        service.backup_and_clear("wrong", requested_by="admin-1")

    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM rooms WHERE room_id = 'v2-room'"
    ).fetchone()["count"] == 1


def test_cutover_creates_verified_backup_before_clearing_only_v2(test_db, tmp_path):
    _seed_room(test_db, "v2-room", "v2")
    _seed_room(test_db, "legacy-room", "v1")
    service = V2CutoverService(test_db, tmp_path)

    result = service.backup_and_clear(CUTOVER_CONFIRMATION, requested_by="admin-1")

    assert result["status"] == "complete"
    assert result["rooms_backed_up"] == 1
    assert result["rooms_cleared"] == 1
    assert len(result["backup_sha256"]) == 64
    backup_path = tmp_path / result["backup_filename"]
    assert backup_path.is_file()
    with zipfile.ZipFile(BytesIO(backup_path.read_bytes())) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema"] == "aikeeper.v2-cutover-backup"
        assert manifest["room_ids"] == ["v2-room"]
        assert "owner-v2-room" not in archive.read("rooms/v2-room.zip").decode(
            "latin1", errors="ignore"
        )

    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM rooms WHERE room_id = 'v2-room'"
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM rooms WHERE room_id = 'legacy-room'"
    ).fetchone()["count"] == 1
    record = test_db.execute(
        "SELECT status, room_count, backup_sha256 FROM v2_cutover_records"
    ).fetchone()
    assert dict(record) == {
        "status": "complete",
        "room_count": 1,
        "backup_sha256": result["backup_sha256"],
    }


def test_cutover_does_not_clear_when_backup_verification_fails(test_db, tmp_path, monkeypatch):
    _seed_room(test_db, "v2-room", "v2")
    service = V2CutoverService(test_db, tmp_path)
    monkeypatch.setattr(service, "_verify_backup", lambda *_: False)

    with pytest.raises(V2CutoverError, match="校验失败"):
        service.backup_and_clear(CUTOVER_CONFIRMATION, requested_by="admin-1")

    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM rooms WHERE room_id = 'v2-room'"
    ).fetchone()["count"] == 1


def test_admin_cutover_endpoint_requires_admin_and_exact_confirmation(test_db, tmp_path):
    test_db.execute(
        "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
        "VALUES ('cutover-admin', 'cutoveradmin', %s, 'Cutover Admin', 'admin')",
        (_hash_password("test123"),),
    )
    _seed_room(test_db, "v2-room", "v2")
    app.state.db = test_db
    app.state.v2_cutover_backup_root = tmp_path
    client = TestClient(app)
    token = client.post(
        "/api/auth/login", json={"username": "cutoveradmin", "password": "test123"}
    ).json()["token"]

    unauthorized = client.post(
        "/api/admin/player-experience-v2/cutover",
        json={"confirmation": CUTOVER_CONFIRMATION},
    )
    assert unauthorized.status_code == 401
    rejected = client.post(
        "/api/admin/player-experience-v2/cutover",
        json={"confirmation": "wrong"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rejected.status_code == 409
    completed = client.post(
        "/api/admin/player-experience-v2/cutover",
        json={"confirmation": CUTOVER_CONFIRMATION},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["rooms_cleared"] == 1
    assert "backup_filename" in completed.json()
