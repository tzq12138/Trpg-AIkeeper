"""Consistency tests for StateService as the single state write entry point."""

import json
import pytest
from src.server.engine.state_service import StateService
from src.server.models import StateChangeSet, CharacterMutationItem


@pytest.fixture
def state_service(test_db):
    return StateService(test_db)


def _setup(state_service, test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('r-cons', 'tok', 'active')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('c-cons', 'r-cons', 'Alice', 'ptok', %s)",
        (json.dumps({"name": "Alice", "hp": 12, "max_hp": 12, "san": 60, "max_san": 60,
                     "mp": 14, "max_mp": 14, "luck": 50}, ensure_ascii=False),),
    )
    test_db.commit()
    state_service.initialize_character_state("c-cons", "r-cons")


class TestStateVersionSingleIncrement:
    def test_one_apply_increments_version_once(self, test_db, state_service):
        _setup(state_service, test_db)
        before = test_db.execute(
            "SELECT state_version FROM rooms WHERE room_id = 'r-cons'"
        ).fetchone()["state_version"]

        state_service.apply_change(
            "r-cons", {"character_id": "c-cons"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c-cons", mutations=[
                    {"op": "replace", "path": "/character/hp", "value": 8}
                ])
            ]),
            reason="test",
        )

        after = test_db.execute(
            "SELECT state_version FROM rooms WHERE room_id = 'r-cons'"
        ).fetchone()["state_version"]
        assert after == before + 1

    def test_empty_change_also_bumps(self, test_db, state_service):
        _setup(state_service, test_db)
        before = test_db.execute(
            "SELECT state_version FROM rooms WHERE room_id = 'r-cons'"
        ).fetchone()["state_version"]
        state_service.apply_change("r-cons", {}, StateChangeSet(), reason="empty")
        after = test_db.execute(
            "SELECT state_version FROM rooms WHERE room_id = 'r-cons'"
        ).fetchone()["state_version"]
        assert after == before + 1


class TestEventSequence:
    def test_state_patch_event_has_sequence(self, test_db, state_service):
        _setup(state_service, test_db)
        result = state_service.apply_change(
            "r-cons", {"character_id": "c-cons"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c-cons", mutations=[
                    {"op": "replace", "path": "/character/hp", "value": 5}
                ])
            ]),
            reason="test",
        )
        assert len(result["events"]) > 0
        # event sequence should be > 0
        event = test_db.execute(
            "SELECT sequence FROM events WHERE sequence = %s", (result["events"][0],)
        ).fetchone()
        assert event is not None


class TestUnsupportedPatch:
    def test_unsupported_mutation_no_error(self, test_db, state_service):
        """Unsupported path should not crash — logged and skipped."""
        _setup(state_service, test_db)
        result = state_service.apply_change(
            "r-cons", {"character_id": "c-cons"},
            StateChangeSet(characterMutations=[
                CharacterMutationItem(characterId="c-cons", mutations=[
                    {"op": "replace", "path": "/character/unknown_field", "value": 999}
                ])
            ]),
            reason="test",
        )
        # Should return without error
        assert result["room_id"] == "r-cons"
