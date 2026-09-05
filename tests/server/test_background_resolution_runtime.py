import asyncio
import json
import os
import uuid
from types import SimpleNamespace

from src.server.db_adapter import PgDatabase
from src.server.player import router_player
from tests.server.test_glass_rain_golden_flow import (
    _create_started_room,
    _GoldenFlowCompiler,
    _insert_v2_action,
    _install_glass_rain,
    _runtime_package,
)


def test_background_pipeline_keeps_ai_guard_and_connection_scoped_state(monkeypatch):
    captured = {}

    class FakeDispatcher:
        def __init__(self, conn, **kwargs):
            captured["dispatcher"] = {"conn": conn, **kwargs}

    class FakeStateService:
        def __init__(self, conn, dispatcher):
            captured["state_service"] = {"conn": conn, "dispatcher": dispatcher}
            captured["state_service_instance"] = self

    class FakePipeline:
        def __init__(self, conn, **kwargs):
            captured["pipeline"] = {"conn": conn, **kwargs}

    monkeypatch.setattr(router_player, "ProjectionDispatcher", FakeDispatcher)
    monkeypatch.setattr(router_player, "ResolutionPipeline", FakePipeline)
    monkeypatch.setattr("src.server.engine.state_service.StateService", FakeStateService)

    connection = object()
    app = SimpleNamespace(state=SimpleNamespace(
        compiler="compiler",
        cache="cache",
        spoiler_guard="guard",
        gateway="gateway",
    ))

    router_player._create_background_pipeline(app, connection)

    assert captured["dispatcher"] == {
        "conn": connection,
        "cache": "cache",
        "spoiler_guard": "guard",
    }
    assert captured["state_service"]["conn"] is connection
    assert captured["pipeline"] == {
        "conn": connection,
        "compiler": "compiler",
        "dispatcher": captured["state_service"]["dispatcher"],
        "spoiler_guard": "guard",
        "gateway": "gateway",
        "state_service": captured["state_service_instance"],
    }


# ── Real async regressions (B1): real PostgreSQL, real pipeline factory ──


def _isolated_pool() -> PgDatabase:
    """Return a PgDatabase pool over the isolated pytest test database."""
    dsn = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper_test",
    )
    pg = PgDatabase(dsn=dsn)
    pg.connect()
    pg.initialize()
    return pg


def _background_app_state(compiler=None) -> SimpleNamespace:
    """Build the app.state shape _create_background_pipeline reads from."""
    return SimpleNamespace(state=SimpleNamespace(
        compiler=compiler or _GoldenFlowCompiler(),
        cache=None,
        spoiler_guard=None,
        gateway=None,
    ))


def _state_version(test_db, room_id: str) -> int:
    row = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    return int(row["state_version"])


def _move_action_id(test_db, room, character_id: str) -> str:
    """Insert one queued move action along the package's first scene edge."""
    package = _runtime_package(test_db, room["room_id"])
    edge = package["semantic_progression_rules"]["edges"][0]
    return _insert_v2_action(
        test_db,
        room_id=room["room_id"],
        character_id=character_id,
        intent_type="move",
        declared_intent="移动向相邻地点。",
        from_scene=edge["from_scene_id"],
        target_scene=edge["to_scene_id"],
    )


def _install_started_room(client, test_db, monkeypatch):
    """Install Glass Rain and return a fully started room with two players."""
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, players, _state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    return room, players


async def _resolve_once(pool, app_state, action_id: str) -> dict:
    """Resolve one action through the production background pipeline factory."""
    conn = pool.get_connection()
    try:
        pipeline = router_player._create_background_pipeline(app_state, conn)
        return await pipeline.resolve_action(action_id)
    finally:
        conn.close()


def test_concurrent_triggers_share_one_authority_commit_and_one_trace(
    client,
    test_db,
    monkeypatch,
):
    """Two workers racing on one action must produce one authoritative commit.

    Both workers claim the same queued action through the shared factory; the
    atomic queued->resolving transition lets exactly one resolve. The other
    worker observes the claimed state and must not roll, mutate or emit again.
    """
    room, players = _install_started_room(client, test_db, monkeypatch)
    character_id = players[0]["character_id"]
    action_id = _move_action_id(test_db, room, character_id)
    before_version = _state_version(test_db, room["room_id"])
    app_state = _background_app_state()

    pool_a = _isolated_pool()
    pool_b = _isolated_pool()
    try:
        async def _race() -> list:
            return await asyncio.gather(
                _resolve_once(pool_a, app_state, action_id),
                _resolve_once(pool_b, app_state, action_id),
            )

        results = asyncio.run(_race())
    finally:
        pool_a.close()
        pool_b.close()

    completed = [result for result in results if result.get("status") == "completed"]
    assert completed, f"no worker completed the action: {results}"
    trace_rows = test_db.execute(
        "SELECT resolution_trace_id FROM resolution_traces WHERE action_id = %s",
        (action_id,),
    ).fetchall()
    assert len(trace_rows) == 1
    resolving_rows = test_db.execute(
        "SELECT status_event_id FROM action_status_events "
        "WHERE action_id = %s AND status = 'resolving'",
        (action_id,),
    ).fetchall()
    assert len(resolving_rows) == 1
    assert _state_version(test_db, room["room_id"]) == before_version + 1


def test_collaboration_batch_state_change_never_hits_state_service_unavailable(
    client,
    test_db,
    monkeypatch,
):
    """A collaboration batch resolving through the factory must keep state_service.

    Previously the collaboration background path built its pipeline without
    state_service/gateway/spoiler_guard, so authoritative state changes were
    rejected with state_service_unavailable. It must now complete the stateful
    action, and private declared intents must never reach the party audience.
    """
    room, players = _install_started_room(client, test_db, monkeypatch)
    character_one = players[0]["character_id"]
    character_two = players[1]["character_id"]

    stateful_action = _move_action_id(test_db, room, character_one)
    contract_id = f"b1-collab-{uuid.uuid4().hex[:12]}"
    test_db.execute(
        "INSERT INTO collaboration_contracts "
        "(contract_id, room_id, initiator_character_id, shared_intent, status, expires_at) "
        "VALUES (%s, %s, %s, %s, 'accepted', NOW() + INTERVAL '1 hour')",
        (contract_id, room["room_id"], character_one, "一起行动"),
    )
    test_db.execute(
        "INSERT INTO collaboration_contract_participants "
        "(contract_id, character_id, role, decision) VALUES "
        "(%s, %s, 'initiator', 'accepted'), (%s, %s, 'invitee', 'accepted')",
        (contract_id, character_one, contract_id, character_two),
    )
    test_db.execute(
        "INSERT INTO collaboration_contract_batches "
        "(contract_id, room_id, action_ids, status) VALUES (%s, %s, %s, 'queued')",
        (
            contract_id,
            room["room_id"],
            json.dumps([stateful_action], ensure_ascii=False),
        ),
    )
    # Terminal-batch checks join through action_drafts -> draft links.
    draft_id = f"draft-{stateful_action}"
    test_db.execute(
        "INSERT INTO action_drafts "
        "(draft_id, room_id, character_id, intent_type, declared_intent) "
        "VALUES (%s, %s, %s, 'move', '移动向相邻地点。')",
        (draft_id, room["room_id"], character_one),
    )
    test_db.execute(
        "INSERT INTO collaboration_contract_drafts "
        "(contract_id, character_id, draft_id) VALUES (%s, %s, %s)",
        (contract_id, character_one, draft_id),
    )
    test_db.commit()

    before_version = _state_version(test_db, room["room_id"])
    pool = _isolated_pool()
    # The collaboration background worker acquires its own connection when
    # app.state.pg_db is present (mirroring the production app shape).
    app_state = _background_app_state()
    app_state.state.pg_db = pool
    try:
        asyncio.run(_resolve_collaboration_batch(app_state, pool, contract_id))
    finally:
        pool.close()

    action_row = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = %s",
        (stateful_action,),
    ).fetchone()
    assert action_row["status"] == "completed", action_row
    result_text = json.dumps(action_row["result"], ensure_ascii=False)
    assert "state_service_unavailable" not in result_text
    batch_row = test_db.execute(
        "SELECT status FROM collaboration_contract_batches WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()
    assert batch_row["status"] == "completed", batch_row
    assert _state_version(test_db, room["room_id"]) == before_version + 1

    # Structural privacy check: party events must not carry raw result internals
    # (mutations) or per-player intent keys. Public narration may legitimately
    # summarize an openly declared action in prose, so we do not blacklist
    # intent words appearing inside public text.
    leaked = test_db.execute(
        "SELECT payload FROM events WHERE room_id = %s AND audience = 'party' "
        "AND (strpos(payload::text, '\"mutations\"') > 0 "
        "OR strpos(payload::text, '\"declared_intent\"') > 0)",
        (room["room_id"],),
    ).fetchall()
    assert leaked == [], f"party audience received raw result internals: {leaked}"


async def _resolve_collaboration_batch(app_state, pool, contract_id: str) -> None:
    conn = pool.get_connection()
    try:
        await router_player._resolve_collaboration_batch_background(app_state, contract_id)
    finally:
        conn.close()
