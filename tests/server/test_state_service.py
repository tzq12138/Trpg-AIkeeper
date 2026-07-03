"""Tests for StateService — unified game-state persistence."""

import json
import pytest
from src.server.engine.state_service import StateService
from src.server.models import StateChangeSet, CharacterMutationItem, SceneChange


class TestStateService:

    @pytest.fixture
    def state_service(self, test_db):
        return StateService(test_db)

    def _setup_room_and_char(self, test_db):
        test_db.execute(
            "INSERT INTO rooms (room_id, owner_token, status) VALUES ('r1', 'tok', 'active')"
        )
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data, account_id) "
            "VALUES ('c1', 'r1', 'Alice', 'ptok', %s, 'acc1')",
            (json.dumps({
                "name": "Alice", "hp": 12, "max_hp": 12,
                "san": 60, "max_san": 60,
                "mp": 14, "max_mp": 14, "luck": 50,
                "skills": {"侦查": 50},
            }, ensure_ascii=False),),
        )
        test_db.commit()

    # ── Initialize ──

    def test_initialize_character_state_creates_runtime(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        runtime = state_service.initialize_character_state("c1", "r1")
        assert runtime is not None
        assert runtime["hp"] == 12
        assert runtime["san"] == 60
        assert runtime["mp"] == 14
        assert runtime["luck"] == 50
        assert runtime["profile_id"] is not None
        assert runtime["version"] == 1

    def test_initialize_character_state_idempotent(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        r1 = state_service.initialize_character_state("c1", "r1")
        r2 = state_service.initialize_character_state("c1", "r1")
        assert r1["hp"] == r2["hp"]
        assert r1["version"] == r2["version"]

    def test_initialize_missing_character_returns_none(self, test_db, state_service):
        result = state_service.initialize_character_state("nonexistent", "r1")
        assert result is None

    # ── Mutations ──

    def test_apply_mutation_hp(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        state_service.initialize_character_state("c1", "r1")
        result = state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c1", mutations=[
                    {"op": "replace", "path": "/character/hp", "value": 8}
                ])
            ]),
            reason="test",
        )
        runtime = state_service.get_runtime_state("c1", "r1")
        assert runtime["hp"] == 8
        assert runtime["version"] == 2
        assert result["state_version"] > 0

    def test_apply_mutation_san(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        state_service.initialize_character_state("c1", "r1")
        state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c1", mutations=[
                    {"op": "replace", "path": "/character/san", "value": 45}
                ])
            ]),
            reason="test",
        )
        runtime = state_service.get_runtime_state("c1", "r1")
        assert runtime["san"] == 45

    def test_apply_mutation_mp(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        state_service.initialize_character_state("c1", "r1")
        state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c1", mutations=[
                    {"op": "replace", "path": "/character/mp", "value": 5}
                ])
            ]),
            reason="test",
        )
        runtime = state_service.get_runtime_state("c1", "r1")
        assert runtime["mp"] == 5

    def test_apply_mutation_luck(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        state_service.initialize_character_state("c1", "r1")
        state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c1", mutations=[
                    {"op": "replace", "path": "/character/luck", "value": 30}
                ])
            ]),
            reason="test",
        )
        runtime = state_service.get_runtime_state("c1", "r1")
        assert runtime["luck"] == 30

    def test_apply_mutation_clamps_hp(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        state_service.initialize_character_state("c1", "r1")
        state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c1", mutations=[
                    {"op": "replace", "path": "/character/hp", "value": -5}
                ])
            ]),
            reason="test",
        )
        runtime = state_service.get_runtime_state("c1", "r1")
        assert runtime["hp"] == 0  # clamped

    def test_apply_mutation_clamps_san(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        state_service.initialize_character_state("c1", "r1")
        state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c1", mutations=[
                    {"op": "replace", "path": "/character/san", "value": 999}
                ])
            ]),
            reason="test",
        )
        runtime = state_service.get_runtime_state("c1", "r1")
        assert runtime["san"] == 60  # clamped to max_san

    def test_apply_mutation_status_tag_add(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        state_service.initialize_character_state("c1", "r1")
        state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c1", mutations=[
                    {"op": "add", "path": "/character/status_tag", "value": "unconscious"}
                ])
            ]),
            reason="test",
        )
        runtime = state_service.get_runtime_state("c1", "r1")
        tags = runtime["status_tags"]
        if isinstance(tags, str):
            tags = json.loads(tags)
        assert "unconscious" in tags

    def test_apply_mutation_status_tag_remove(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        state_service.initialize_character_state("c1", "r1")
        # Add first
        state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c1", mutations=[
                    {"op": "add", "path": "/character/status_tag", "value": "unconscious"}
                ])
            ]),
            reason="test",
        )
        # Remove
        state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c1", mutations=[
                    {"op": "remove", "path": "/character/status_tag", "value": "unconscious"}
                ])
            ]),
            reason="test",
        )
        runtime = state_service.get_runtime_state("c1", "r1")
        tags = runtime["status_tags"]
        if isinstance(tags, str):
            tags = json.loads(tags)
        assert "unconscious" not in tags

    # ── Scene Changes ──

    def test_apply_scene_change(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(sceneChanges=SceneChange(
                currentScene="warehouse_1",
                visitedScenesAdd=["entrance"],
            )),
            reason="test",
        )
        scene = state_service.get_scene_state("r1")
        assert scene is not None
        assert scene["current_scene"] == "warehouse_1"
        visited = scene["visited_scenes"]
        if isinstance(visited, str):
            visited = json.loads(visited)
        assert "warehouse_1" in visited
        assert "entrance" in visited

    def test_apply_scene_change_facts_and_triggers(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(sceneChanges=SceneChange(
                currentScene="lab",
                triggerFired="alarm_triggered",
                publicFactsAdd=["门已经打开"],
                variableSet={"alarm_count": 1},
                bgm="tense_bgm",
            )),
            reason="test",
        )
        scene = state_service.get_scene_state("r1")
        triggers = scene["triggered_triggers"]
        facts = scene["public_facts"]
        variables = scene["scene_variables"]
        if isinstance(triggers, str):
            triggers = json.loads(triggers)
        if isinstance(facts, str):
            facts = json.loads(facts)
        if isinstance(variables, str):
            variables = json.loads(variables)
        assert "alarm_triggered" in triggers
        assert "门已经打开" in facts
        assert variables.get("alarm_count") == 1
        assert scene["current_bgm"] == "tense_bgm"

    # ── Version & Events ──

    def test_bumps_room_version(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        before = test_db.execute(
            "SELECT state_version FROM rooms WHERE room_id = 'r1'"
        ).fetchone()["state_version"]
        state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(),
            reason="test",
        )
        after = test_db.execute(
            "SELECT state_version FROM rooms WHERE room_id = 'r1'"
        ).fetchone()["state_version"]
        assert after == before + 1

    def test_apply_change_writes_events(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        state_service.initialize_character_state("c1", "r1")
        result = state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c1", mutations=[
                    {"op": "replace", "path": "/character/hp", "value": 5}
                ])
            ]),
            reason="test",
        )
        assert len(result["events"]) > 0
        event = test_db.execute(
            "SELECT * FROM events WHERE sequence = %s", (result["events"][0],)
        ).fetchone()
        assert event is not None
        assert event["event_type"] == "s2c_state_patch"

    def test_apply_change_missing_room_raises(self, test_db, state_service):
        with pytest.raises(ValueError, match="not found"):
            state_service.apply_change(
                "nonexistent", {"character_id": "c1"},
                StateChangeSet(),
                reason="test",
            )

    def test_version_bumps_on_each_apply(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        state_service.initialize_character_state("c1", "r1")
        assert state_service.get_runtime_state("c1", "r1")["version"] == 1
        state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c1", mutations=[
                    {"op": "replace", "path": "/character/hp", "value": 10}
                ])
            ]),
            reason="t1",
        )
        assert state_service.get_runtime_state("c1", "r1")["version"] == 2
        state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c1", mutations=[
                    {"op": "replace", "path": "/character/san", "value": 50}
                ])
            ]),
            reason="t2",
        )
        assert state_service.get_runtime_state("c1", "r1")["version"] == 3

    # ── Lazy init ──

    def test_lazy_init_on_mutation(self, test_db, state_service):
        """Runtime state is created lazily if missing when a mutation arrives."""
        self._setup_room_and_char(test_db)
        # Don't call initialize_character_state first
        state_service.apply_change(
            "r1", {"character_id": "c1"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c1", mutations=[
                    {"op": "replace", "path": "/character/hp", "value": 3}
                ])
            ]),
            reason="test",
        )
        runtime = state_service.get_runtime_state("c1", "r1")
        assert runtime is not None
        assert runtime["hp"] == 3

    # ── Profile ──

    def test_profile_created_for_account(self, test_db, state_service):
        self._setup_room_and_char(test_db)
        state_service.initialize_character_state("c1", "r1")
        profiles = test_db.execute(
            "SELECT * FROM character_profiles WHERE account_id = 'acc1'"
        ).fetchall()
        assert len(profiles) == 1
        assert profiles[0]["name"] == "Alice"
