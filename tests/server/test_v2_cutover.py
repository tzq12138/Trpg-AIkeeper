import json
import zipfile
from decimal import Decimal
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
        "INSERT INTO events "
        "(room_id, event_type, audience, payload, action_id, state_version) "
        "VALUES (%s, 's2c_public_observation', 'party', %s, %s, 0)",
        (
            room_id,
            json.dumps({"text": "现场仍有余温"}, ensure_ascii=False),
            f"action-{room_id}",
        ),
    )


def test_cutover_requires_exact_confirmation_and_keeps_rooms(test_db, tmp_path):
    _seed_room(test_db, "v2-room", "v2")
    service = V2CutoverService(test_db, tmp_path)

    with pytest.raises(V2CutoverError, match="确认短语"):
        service.backup_and_clear("wrong", requested_by="admin-1")

    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM rooms WHERE room_id = 'v2-room'"
    ).fetchone()["count"] == 1


def test_cutover_creates_verified_backup_before_clearing_all_existing_rooms(
    test_db,
    tmp_path,
):
    _seed_room(test_db, "v2-room", "v2")
    _seed_room(test_db, "legacy-room", "v1")
    reveal_event_sequence = test_db.execute(
        "SELECT sequence FROM events WHERE room_id = 'v2-room'"
    ).fetchone()["sequence"]
    test_db.execute(
        "INSERT INTO fact_reveals "
        "(reveal_id, room_id, fact_id, content_item_id, fact_text, citation, "
        "audience, source_action_id, state_version, event_sequence, trigger_snapshot) "
        "VALUES ('cutover-reveal', 'v2-room', 'cutover-fact', 'cutover-fact', "
        "'cutover-fact-reveal-canary', '{}', 'party', 'action-v2-room', 0, %s, '{}')",
        (reveal_event_sequence,),
    )
    test_db.execute(
        "INSERT INTO inventory (id, character_id, room_id, name, source) "
        "VALUES ('cutover-inventory', 'char-v2-room', 'v2-room', "
        "'切换备份金丝雀', 'cutover-live-state-canary')"
    )
    test_db.execute(
        "INSERT INTO inventory_transfer_requests "
        "(transfer_id, room_id, item_id, from_character_id, to_character_id, "
        "item_name, quantity) "
        "VALUES ('cutover-transfer', 'v2-room', 'cutover-inventory', "
        "'char-v2-room', 'char-legacy-room', '切换备份金丝雀', 1)"
    )
    test_db.execute(
        "INSERT INTO campaign_sessions "
        "(campaign_session_id, room_id, status, started_by_character_id) "
        "VALUES ('cutover-session', 'v2-room', 'ended', 'char-v2-room')"
    )
    test_db.execute(
        "INSERT INTO session_summaries "
        "(session_summary_id, campaign_session_id, room_id, summary_text, confidence) "
        "VALUES ('cutover-summary', 'cutover-session', 'v2-room', "
        "'切换会话摘要', %s)",
        (Decimal("0.875"),),
    )
    test_db.execute(
        "INSERT INTO session_summary_citations "
        "(session_summary_citation_id, session_summary_id, citation_label) "
        "VALUES ('cutover-summary-citation', 'cutover-summary', "
        "'cutover-summary-citation-canary')"
    )
    test_db.execute(
        "INSERT INTO player_notes "
        "(note_id, room_id, character_id, title_ciphertext, body_ciphertext) "
        "VALUES ('cutover-note', 'v2-room', 'char-v2-room', "
        "'private-title', 'private-body')"
    )
    test_db.execute(
        "INSERT INTO note_attachments "
        "(note_attachment_id, note_id, filename_ciphertext, content_type, "
        "content_ciphertext) "
        "VALUES ('cutover-note-attachment', 'cutover-note', "
        "'private-filename', 'application/x-cutover-note-canary', "
        "'private-content')"
    )
    test_db.execute(
        "INSERT INTO evidence_cards "
        "(evidence_card_id, room_id, created_by_character_id, title, body) "
        "VALUES ('cutover-evidence', 'v2-room', 'char-v2-room', "
        "'切换证据', '切换证据正文')"
    )
    test_db.execute(
        "INSERT INTO evidence_references "
        "(evidence_reference_id, evidence_card_id, reference_type, reference_id, citation) "
        "VALUES ('cutover-evidence-reference', 'cutover-evidence', "
        "'cutover-evidence-reference-canary', 'cutover-note', '{}')"
    )
    test_db.commit()
    service = V2CutoverService(test_db, tmp_path)

    result = service.backup_and_clear(CUTOVER_CONFIRMATION, requested_by="admin-1")

    assert result["status"] == "complete"
    assert result["rooms_backed_up"] == 2
    assert result["rooms_cleared"] == 2
    assert len(result["backup_sha256"]) == 64
    backup_path = tmp_path / result["backup_filename"]
    assert backup_path.is_file()
    with zipfile.ZipFile(BytesIO(backup_path.read_bytes())) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema"] == "aikeeper.v2-cutover-backup"
        assert manifest["room_ids"] == ["legacy-room", "v2-room"]
        assert set(archive.namelist()) == {"manifest.json", "live_state.json"}
        assert manifest["table_inventory"]["note_attachments"]["count"] == 1
        assert len(manifest["table_inventory"]["note_attachments"]["sha256"]) == 64
        assert manifest["table_inventory"]["session_summary_citations"]["count"] == 1
        assert manifest["table_inventory"]["evidence_references"]["count"] == 1
        assert manifest["table_inventory"]["fact_reveals"]["count"] == 1
        assert manifest["table_inventory"]["session_attendance"]["count"] == 0
        live_state = json.loads(archive.read("live_state.json"))
        rendered_live_state = json.dumps(live_state, ensure_ascii=False)
        assert "cutover-live-state-canary" in rendered_live_state
        assert "cutover-transfer" in rendered_live_state
        assert "cutover-summary-citation-canary" in rendered_live_state
        assert "application/x-cutover-note-canary" in rendered_live_state
        assert "cutover-evidence-reference-canary" in rendered_live_state
        assert "cutover-fact-reveal-canary" in rendered_live_state
        assert '"confidence": "0.875"' in rendered_live_state
        assert "owner-v2-room" not in rendered_live_state
        assert "player-v2-room" not in rendered_live_state
        assert "private-title" not in rendered_live_state
        assert "private-body" not in rendered_live_state
        assert "private-filename" not in rendered_live_state
        assert "private-content" not in rendered_live_state

    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM rooms WHERE room_id = 'v2-room'"
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM rooms WHERE room_id = 'legacy-room'"
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM inventory_transfer_requests "
        "WHERE transfer_id = 'cutover-transfer'"
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM fact_reveals WHERE reveal_id = 'cutover-reveal'"
    ).fetchone()["count"] == 0
    for table, key, value in (
        ("session_summary_citations", "session_summary_citation_id", "cutover-summary-citation"),
        ("note_attachments", "note_attachment_id", "cutover-note-attachment"),
        ("evidence_references", "evidence_reference_id", "cutover-evidence-reference"),
    ):
        assert test_db.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE {key} = %s",
            (value,),
        ).fetchone()["count"] == 0
    record = test_db.execute(
        "SELECT status, room_count, backup_sha256 FROM v2_cutover_records"
    ).fetchone()
    assert dict(record) == {
        "status": "complete",
        "room_count": 2,
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
