"""B4 — real Session Zero projection probes and absent-policy freeze (D19).

Covers AIO-SZ-001~008 through the production APIs:
- the five confirmation buttons alone never open an AI-only room unless the
  engine-issued probes (private/party projection, device recovery) are valid;
- private probes cannot be confirmed by another player; stale devices revoke
  validity; a client claiming success without a server record is rejected;
- device recovery requires a real reconnect watermark;
- absent policy is frozen at start (snapshot v1) and later changes append
  independently versioned snapshots.
"""

import uuid

from tests.server.test_glass_rain_golden_flow import _install_glass_rain

SESSION_STEPS = (
    "character_rules",
    "safety",
    "ai_host",
    "private_data",
    "connection",
)


def _setup_prestart_room(client, test_db, monkeypatch):
    """Install Glass Rain and join two players into an unstarted AI-only room."""
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    created = client.post(
        "/api/rooms",
        headers={"Authorization": f"Bearer {tokens['admin']}"},
        json={"scenario_id": installed["scenarioId"]},
    )
    assert created.status_code == 200, created.text
    room = created.json()
    players = []
    for ordinal, player_key in enumerate(("player_1", "player_2")):
        joined = client.post(
            f"/api/player/rooms/{room['room_id']}/join-with-character",
            headers={"Authorization": f"Bearer {tokens[player_key]}"},
            data={"player_name": f"Player {ordinal + 1}", "template_id": templates[ordinal]},
        )
        assert joined.status_code == 200, joined.text
        players.append(joined.json())
    return room, players


def _claim_device(client, player, device_id: str):
    response = client.post(
        "/api/player/device-sessions/claim",
        headers={"X-Room-Token": player["player_token"]},
        json={"device_id": device_id, "takeover": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _confirm_all_steps(client, player, room):
    headers = {"X-Room-Token": player["player_token"]}
    for step in SESSION_STEPS:
        confirmation = {"confirmed": True}
        if step == "safety":
            confirmation["contract_hash"] = room["risk_contract_hash"]
        confirmed = client.post(
            f"/api/player/session-zero/{step}",
            headers=headers,
            json=confirmation,
        )
        assert confirmed.status_code == 200, confirmed.text


def _ready_up(client, player):
    ready = client.post(
        "/api/player/intent",
        headers={"X-Room-Token": player["player_token"]},
        json={
            "action_id": f"probe-ready-{uuid.uuid4().hex[:10]}",
            "intent_type": "ready_toggle",
            "declared_intent": "准备就绪",
        },
    )
    assert ready.status_code == 202, ready.text


def _latest_probes(client, player):
    response = client.get(
        "/api/player/session-zero/probes",
        headers={"X-Room-Token": player["player_token"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _confirm_all_probes(client, player, probes=None):
    """Confirm every issued probe, using a real reconnect watermark for recovery."""
    headers = {"X-Room-Token": player["player_token"]}
    payload = probes or _latest_probes(client, player)
    for probe in payload["probes"]:
        if probe["valid"] or probe["probe_id"] is None:
            continue
        body = {"probe_id": probe["probe_id"], "probe_type": probe["probe_type"]}
        if probe["probe_type"] == "device_recovery":
            reconnect = client.get("/api/player/reconnect", headers=headers)
            assert reconnect.status_code == 200, reconnect.text
            body["watermark"] = reconnect.json().get("last_sequence", 0)
        confirmed = client.post(
            "/api/player/session-zero/probes/confirm",
            headers=headers,
            json=body,
        )
        assert confirmed.status_code == 200, confirmed.text


def _start_room(client, room):
    started = client.post(
        f"/api/rooms/{room['room_id']}/start",
        headers={"X-Owner-Token": room["owner_token"]},
    )
    return started


def _session_zero(client, player):
    response = client.get(
        "/api/player/session-zero",
        headers={"X-Room-Token": player["player_token"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_five_buttons_without_valid_probes_still_block_start(
    client,
    test_db,
    monkeypatch,
):
    """AIO-SZ-001/002/004/007: buttons alone never open the room."""
    room, players = _setup_prestart_room(client, test_db, monkeypatch)
    for player in players:
        _claim_device(client, player, "device-A")
        _confirm_all_steps(client, player, room)
        _ready_up(client, player)

    status = _session_zero(client, players[0])
    assert status["complete"] is False
    assert set(status["missing_probes"]) == {
        "private_projection",
        "party_projection",
        "device_recovery",
    }

    rejected = _start_room(client, room)
    assert rejected.status_code == 409, rejected.text
    detail = rejected.json()["detail"]
    assert detail["code"] == "AI_ONLY_SESSION_ZERO_INCOMPLETE"
    missing = {
        item
        for character in detail["missing"]
        for item in character["missing"]
    }
    assert "probe_private_projection" in missing
    assert "probe_device_recovery" in missing


def test_valid_probes_then_start_succeeds(client, test_db, monkeypatch):
    """AIO-SZ-001: complete confirmations + valid probes open the room."""
    room, players = _setup_prestart_room(client, test_db, monkeypatch)
    for player in players:
        _claim_device(client, player, "device-A")
        _confirm_all_steps(client, player, room)
        _confirm_all_probes(client, player)
        _ready_up(client, player)

    status = _session_zero(client, players[0])
    assert status["complete"] is True, status

    started = _start_room(client, room)
    assert started.status_code == 200, started.text


def test_other_player_cannot_confirm_private_probe(client, test_db, monkeypatch):
    """Private probes are owned by the probed character (no cross-leak)."""
    room, players = _setup_prestart_room(client, test_db, monkeypatch)
    for player in players:
        _claim_device(client, player, "device-A")
    _confirm_all_steps(client, players[0], room)
    payload = _latest_probes(client, players[0])
    private_probe = next(
        probe for probe in payload["probes"]
        if probe["probe_type"] == "private_projection"
    )
    intruder = client.post(
        "/api/player/session-zero/probes/confirm",
        headers={"X-Room-Token": players[1]["player_token"]},
        json={
            "probe_id": private_probe["probe_id"],
            "probe_type": "private_projection",
        },
    )
    assert intruder.status_code == 409, intruder.text
    assert intruder.json()["detail"]["code"] == "probe_not_found"


def test_unknown_probe_id_claim_without_server_record_is_rejected(
    client,
    test_db,
    monkeypatch,
):
    """Client-claimed success without a server-issued record must be rejected."""
    room, players = _setup_prestart_room(client, test_db, monkeypatch)
    _claim_device(client, players[0], "device-A")
    fabricated = client.post(
        "/api/player/session-zero/probes/confirm",
        headers={"X-Room-Token": players[0]["player_token"]},
        json={
            "probe_id": str(uuid.uuid4()),
            "probe_type": "private_projection",
        },
    )
    assert fabricated.status_code == 409, fabricated.text
    assert fabricated.json()["detail"]["code"] == "probe_not_found"


def test_device_takeover_invalidates_confirmed_probes_until_reconfirmed(
    client,
    test_db,
    monkeypatch,
):
    """A stale device's confirmations cannot open the room (AIO-SZ-007/008)."""
    room, players = _setup_prestart_room(client, test_db, monkeypatch)
    for player in players:
        _claim_device(client, player, "device-A")
    _confirm_all_steps(client, players[0], room)
    _confirm_all_probes(client, players[0])
    _ready_up(client, players[0])
    _claim_device(client, players[0], "device-B")  # takeover on a new device

    status = _session_zero(client, players[0])
    assert status["complete"] is False, status
    reasons = {probe["probe_type"]: probe["reason"] for probe in
               _latest_probes(client, players[0])["probes"]}
    assert reasons["private_projection"] == "controller_device_changed"

    # Re-issue probes from the new controller device and confirm again.
    _confirm_all_steps(client, players[0], room)
    _confirm_all_probes(client, players[0])
    status = _session_zero(client, players[0])
    assert status["complete"] is True, status


def test_device_recovery_requires_real_reconnect_watermark(
    client,
    test_db,
    monkeypatch,
):
    """Recovery probes need a watermark >= the issued watermark."""
    room, players = _setup_prestart_room(client, test_db, monkeypatch)
    _claim_device(client, players[0], "device-A")
    _confirm_all_steps(client, players[0], room)
    probes = _latest_probes(client, players[0])
    recovery = next(
        probe for probe in probes["probes"]
        if probe["probe_type"] == "device_recovery"
    )
    insufficient = client.post(
        "/api/player/session-zero/probes/confirm",
        headers={"X-Room-Token": players[0]["player_token"]},
        json={
            "probe_id": recovery["probe_id"],
            "probe_type": "device_recovery",
            "watermark": 0,
        },
    )
    if recovery["issued_watermark"] and recovery["issued_watermark"] > 0:
        assert insufficient.status_code == 409, insufficient.text
        assert insufficient.json()["detail"]["code"] == "probe_watermark_insufficient"
    else:
        assert insufficient.status_code == 200, insufficient.text


def test_absent_policy_freeze_keeps_baseline_and_versions_later_changes(
    client,
    test_db,
    monkeypatch,
):
    """AIO-SZ-005: initial policy is frozen; later changes append versions."""
    room, players = _setup_prestart_room(client, test_db, monkeypatch)
    headers = {"X-Room-Token": players[0]["player_token"]}
    for player in players:
        _claim_device(client, player, "device-A")
        _confirm_all_steps(client, player, room)
        _confirm_all_probes(client, player)
        _ready_up(client, player)

    changed = client.patch(
        "/api/player/settings",
        headers=headers,
        json={"absent_policy": "maintain_existing"},
    )
    assert changed.status_code == 200, changed.text

    started = _start_room(client, room)
    assert started.status_code == 200, started.text

    # Player 1 changed the policy before start: the freeze seals that value as
    # v1 without overwriting its traceable origin.
    frozen = test_db.execute(
        "SELECT absent_policy, snapshot_version, reason FROM absent_policy_snapshots "
        "WHERE room_id = %s AND character_id = %s AND snapshot_version = 1",
        (room["room_id"], players[0]["character_id"]),
    ).fetchone()
    assert frozen is not None
    assert frozen["absent_policy"] == "maintain_existing"
    assert frozen["reason"] == "player_settings_change"

    # Player 2 never touched settings: the start transaction itself freezes the
    # default baseline with the session_zero_freeze reason (AIO-SZ-005).
    default_frozen = test_db.execute(
        "SELECT absent_policy, snapshot_version, reason FROM absent_policy_snapshots "
        "WHERE room_id = %s AND character_id = %s AND snapshot_version = 1",
        (room["room_id"], players[1]["character_id"]),
    ).fetchone()
    assert default_frozen is not None
    assert default_frozen["absent_policy"] == "idle"
    assert default_frozen["reason"] == "session_zero_freeze"

    # A later effective change appends a new version and leaves v1 untouched.
    later = client.patch(
        "/api/player/settings",
        headers=headers,
        json={"absent_policy": "idle"},
    )
    assert later.status_code == 200, later.text
    rows = test_db.execute(
        "SELECT absent_policy, snapshot_version, reason FROM absent_policy_snapshots "
        "WHERE room_id = %s AND character_id = %s ORDER BY snapshot_version",
        (room["room_id"], players[0]["character_id"]),
    ).fetchall()
    versions = [(row["snapshot_version"], row["absent_policy"], row["reason"]) for row in rows]
    assert (1, "maintain_existing", "player_settings_change") in versions
    assert (2, "idle", "player_settings_change") in versions
    settings = client.get("/api/player/settings", headers=headers).json()
    assert settings["absent_policy"] == "idle"
