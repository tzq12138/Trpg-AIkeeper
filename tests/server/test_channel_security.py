"""Channel security tests: player WS catch-up audience filtering."""

import json
import pytest
from src.server.events.event_log import EventLog


class TestPlayerCatchUpFiltering:
    """Verify that player WS catch-up filters events by audience and character."""

    def _setup(self, test_db):
        test_db.execute(
            "INSERT INTO rooms (room_id, owner_token, status) "
            "VALUES ('ch-sec-room', 'tok-cs', 'active')"
        )
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
            "VALUES ('ch-alice', 'ch-sec-room', 'Alice', 'pt-alice', 'joined')"
        )
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
            "VALUES ('ch-bob', 'ch-sec-room', 'Bob', 'pt-bob', 'joined')"
        )
        test_db.commit()
        return EventLog(test_db)

    def test_player_catchup_excludes_host_events(self, test_db):
        """Player catch-up must NOT include host-audience events."""
        elog = self._setup(test_db)
        # Write a host-only event
        elog.log_event("ch-sec-room", "s2c_host_snapshot", "host",
                       {"data": "secret"})
        # Write a party event
        elog.log_event("ch-sec-room", "s2c_public_observation", "party",
                       {"narrative": "hello"})

        events = elog.get_events_for_player("ch-sec-room", "ch-alice")
        event_types = [e.event_type for e in events]
        assert "s2c_host_snapshot" not in event_types, "Host events leaked to player"
        assert "s2c_public_observation" in event_types, "Party events should be visible"

    def test_player_catchup_excludes_other_player_private(self, test_db):
        """Player A must NOT receive player-audience events for Player B."""
        elog = self._setup(test_db)
        # Alice gets a private notice
        elog.log_event("ch-sec-room", "s2c_private_notice", "player",
                       {"character_id": "ch-alice", "text": "Alice secret"})
        # Bob gets a private notice
        elog.log_event("ch-sec-room", "s2c_private_notice", "player",
                       {"character_id": "ch-bob", "text": "Bob secret"})

        # Alice's catch-up should include her own but not Bob's
        alice_events = elog.get_events_for_player("ch-sec-room", "ch-alice")
        texts = [json.loads(e.payload) if isinstance(e.payload, str) else e.payload
                 for e in alice_events]
        text_values = [t.get("text", "") for t in texts if isinstance(t, dict)]
        assert "Alice secret" in text_values, "Alice should see her own private notice"
        assert "Bob secret" not in text_values, "Alice must not see Bob's private notice"

    def test_player_catchup_receives_party_events(self, test_db):
        """Player catch-up should include party/system audience events."""
        elog = self._setup(test_db)
        elog.log_event("ch-sec-room", "s2c_team_message", "party",
                       {"characterId": "ch-bob", "text": "Hello team"})
        elog.log_event("ch-sec-room", "s2c_room_lobby_snapshot", "party",
                       {"room_status": "active"})

        events = elog.get_events_for_player("ch-sec-room", "ch-alice")
        event_types = [e.event_type for e in events]
        assert "s2c_team_message" in event_types
        assert "s2c_room_lobby_snapshot" in event_types

    def test_player_catchup_receives_own_player_events(self, test_db):
        """Player should receive player-audience events that match their character_id."""
        elog = self._setup(test_db)
        elog.log_event("ch-sec-room", "s2c_state_patch", "player",
                       {"character_id": "ch-alice", "hp": 8})
        elog.log_event("ch-sec-room", "s2c_action_completed", "player",
                       {"character_id": "ch-alice", "result": "success"})

        events = elog.get_events_for_player("ch-sec-room", "ch-alice")
        assert len(events) >= 2
        for e in events:
            assert e.audience in ("party", "player", "system")
