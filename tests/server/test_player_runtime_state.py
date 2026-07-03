"""Tests for player runtime state persistence and separation from xlsx_data."""

import json
import pytest
from src.server.engine.state_service import StateService
from src.server.models import StateChangeSet, CharacterMutationItem


@pytest.fixture
def state_service(test_db):
    return StateService(test_db)


def _setup(state_service, test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('r-runtime', 'tok', 'active')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('c-rt', 'r-runtime', 'Alice', 'ptok', %s)",
        (json.dumps({"name": "Alice", "hp": 12, "max_hp": 12, "san": 60, "max_san": 60,
                     "mp": 14, "max_mp": 14, "luck": 50, "skills": {"侦查": 50}}, ensure_ascii=False),),
    )
    test_db.commit()


class TestRuntimeStateInit:
    def test_init_from_xlsx(self, test_db, state_service):
        _setup(state_service, test_db)
        runtime = state_service.initialize_character_state("c-rt", "r-runtime")
        assert runtime is not None
        assert runtime["hp"] == 12
        assert runtime["hp_max"] == 12
        assert runtime["san"] == 60
        assert runtime["luck"] == 50

    def test_xlsx_unchanged_after_hp_change(self, test_db, state_service):
        _setup(state_service, test_db)
        state_service.initialize_character_state("c-rt", "r-runtime")

        # Get original xlsx
        char_before = test_db.execute(
            "SELECT xlsx_data FROM characters WHERE character_id = 'c-rt'"
        ).fetchone()

        # Apply HP change via StateService
        state_service.apply_change(
            "r-runtime", {"character_id": "c-rt"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c-rt", mutations=[
                    {"op": "replace", "path": "/character/hp", "value": 5}
                ])
            ]),
            reason="test",
        )

        # xlsx_data should be unchanged
        char_after = test_db.execute(
            "SELECT xlsx_data FROM characters WHERE character_id = 'c-rt'"
        ).fetchone()
        assert char_before["xlsx_data"] == char_after["xlsx_data"]

        # Runtime state should have the new HP
        runtime = state_service.get_runtime_state("c-rt", "r-runtime")
        assert runtime["hp"] == 5

    def test_runtime_state_persists_after_multiple_changes(self, test_db, state_service):
        _setup(state_service, test_db)
        state_service.initialize_character_state("c-rt", "r-runtime")

        state_service.apply_change(
            "r-runtime", {"character_id": "c-rt"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c-rt", mutations=[
                    {"op": "replace", "path": "/character/hp", "value": 3}
                ])
            ]),
            reason="hit1",
        )
        state_service.apply_change(
            "r-runtime", {"character_id": "c-rt"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c-rt", mutations=[
                    {"op": "replace", "path": "/character/san", "value": 25}
                ])
            ]),
            reason="hit2",
        )

        runtime = state_service.get_runtime_state("c-rt", "r-runtime")
        assert runtime["hp"] == 3
        assert runtime["san"] == 25
        assert runtime["version"] == 3  # init=1, hit1=2, hit2=3
