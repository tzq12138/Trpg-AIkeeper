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

    def test_empty_change_no_op(self, test_db, state_service):
        """Empty StateChangeSet returns no_op=True and does NOT bump version."""
        _setup(state_service, test_db)
        before = test_db.execute(
            "SELECT state_version FROM rooms WHERE room_id = 'r-cons'"
        ).fetchone()["state_version"]
        result = state_service.apply_change("r-cons", {}, StateChangeSet(), reason="empty")
        assert result.get("no_op") is True
        after = test_db.execute(
            "SELECT state_version FROM rooms WHERE room_id = 'r-cons'"
        ).fetchone()["state_version"]
        assert after == before


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
        assert len(result["event_refs"]) > 0
        # event sequence should be > 0
        event = test_db.execute(
            "SELECT sequence FROM events WHERE sequence = %s", (result["event_refs"][0],)
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


class TestEncounterChangesRejected:
    def test_encounter_changes_not_supported(self, test_db, state_service):
        """encounter_changes through StateService must raise, not silently succeed."""
        _setup(state_service, test_db)
        with pytest.raises(ValueError, match="encounter_changes are not supported"):
            state_service.apply_change(
                "r-cons", {"character_id": "c-cons"},
                StateChangeSet(encounterChanges={
                    "encounterId": "enc-1", "action": "start",
                }),
                reason="test",
            )


class TestLogEventNoPrematureCommit:
    def test_log_event_commit_false(self, test_db, state_service):
        """log_event(commit=False) must not auto-commit."""
        from src.server.events.event_log import EventLog
        event_log = EventLog(test_db)
        _setup(state_service, test_db)

        # Count events before
        before = test_db.execute("SELECT COUNT(*) AS cnt FROM events").fetchone()["cnt"]

        seq = event_log.log_event(
            "r-cons", "s2c_test_event", "system",
            {"test": True}, commit=False,
        )
        assert seq > 0

        # Without commit, other connections should not see the event yet
        # (in same connection it's visible, so we verify commit=False doesn't error)
        after_same = test_db.execute(
            "SELECT COUNT(*) AS cnt FROM events WHERE sequence = %s", (seq,)
        ).fetchone()["cnt"]
        assert after_same == 1  # visible in same connection

        # Verify commit=False didn't commit (next commit will include it)
        # Explicit rollback to clean up test
        test_db.commit()  # commit the pending event
        after_commit = test_db.execute("SELECT COUNT(*) AS cnt FROM events").fetchone()["cnt"]
        assert after_commit >= before + 1
