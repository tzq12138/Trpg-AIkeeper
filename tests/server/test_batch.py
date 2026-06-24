from src.server.batch import BatchCollector


def test_collector_creates_batch_after_timeout():
    collector = BatchCollector(window_seconds=0)
    collector.add_action("room-1", {"action_id": "a1", "character_id": "c1", "intent": "look"})
    batch = collector.maybe_create_batch("room-1")
    assert batch is not None
    assert len(batch["actions"]) == 1


def test_collector_merges_multiple_actions():
    collector = BatchCollector(window_seconds=0)
    collector.add_action("room-1", {"action_id": "a1", "character_id": "c1", "intent": "look"})
    collector.add_action("room-1", {"action_id": "a2", "character_id": "c2", "intent": "search"})
    batch = collector.maybe_create_batch("room-1")
    assert batch is not None
    assert len(batch["actions"]) == 2


def test_collector_different_rooms():
    collector = BatchCollector(window_seconds=0)
    collector.add_action("room-1", {"action_id": "a1", "character_id": "c1", "intent": "look"})
    collector.add_action("room-2", {"action_id": "a2", "character_id": "c2", "intent": "search"})
    batch1 = collector.maybe_create_batch("room-1")
    batch2 = collector.maybe_create_batch("room-2")
    assert batch1["actions"][0]["action_id"] == "a1"
    assert batch2["actions"][0]["action_id"] == "a2"


def test_collector_no_batch_when_window_not_elapsed():
    collector = BatchCollector(window_seconds=999)
    collector.add_action("room-1", {"action_id": "a1", "character_id": "c1", "intent": "look"})
    batch = collector.maybe_create_batch("room-1")
    assert batch is None


def test_collector_batch_at_max_actions():
    collector = BatchCollector(window_seconds=999)
    for i in range(4):
        collector.add_action("room-1", {"action_id": f"a{i}", "character_id": "c1", "intent": "look"})
    batch = collector.maybe_create_batch("room-1")
    assert batch is not None
    assert len(batch["actions"]) == 4
