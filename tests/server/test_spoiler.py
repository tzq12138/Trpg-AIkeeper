import json
from src.server.spoiler_control import SpoilerController, SPOILER_VISIBILITY


def _setup_db(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, spoiler_level) VALUES ('room-1', 'token', 'standard')"
    )
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, spoiler_level) VALUES ('room-s', 'token', 'strict')"
    )
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, spoiler_level) VALUES ('room-c', 'token', 'cinematic')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-1', 'room-1', 'Alice', 'tok-1')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-s', 'room-s', 'Alice', 'tok-s')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-c', 'room-c', 'Alice', 'tok-c')"
    )
    test_db.execute(
        "INSERT INTO clues (clue_id, room_id, character_id, text, source) "
        "VALUES ('clue-1', 'room-1', 'char-1', 'blood stain', 'floor')"
    )
    test_db.execute(
        "INSERT INTO clues (clue_id, room_id, character_id, text, source) "
        "VALUES ('clue-s1', 'room-s', 'char-s', 'blood stain', 'floor')"
    )
    test_db.execute(
        "INSERT INTO clues (clue_id, room_id, character_id, text, source) "
        "VALUES ('clue-c1', 'room-c', 'char-c', 'blood stain', 'floor')"
    )
    test_db.commit()


def _make_scenario():
    return {
        "scenario_id": "sc-1",
        "title": "黑暗庄园",
        "raw_text": "一座维多利亚时代的古老庄园，走廊尽头传来微弱的光。",
        "knowledge_graph": json.dumps({
            "scene_description": "昏暗的走廊，墙纸剥落，地上散落着旧报纸。",
            "clues": [
                {"clue_id": "clue-1", "text": "地板上的暗红色血迹", "is_hidden": False},
                {"clue_id": "clue-2", "text": "日记本中的密信", "is_hidden": True},
            ],
            "npcs": [
                {"npc_id": "npc-1", "name": "管家", "description": "一个沉默寡言的老人", "is_hidden": False},
                {"npc_id": "npc-2", "name": "幕后黑手", "public_description": "一个神秘身影",
                 "description": "庄园主的弟弟", "is_hidden": True},
            ],
            "truth_summary": "管家是凶手，为了遗产杀害了庄园主。",
            "atmosphere": "压抑、阴冷",
            "public_observations": ["走廊尽头有微光闪烁"],
        }),
    }


def test_strict_mode_hides_most_info(test_db):
    _setup_db(test_db)
    ctrl = SpoilerController(test_db)
    scenario = _make_scenario()

    filtered = ctrl.filter_for_player(scenario, "char-1", ["clue-1"], "strict")

    assert len(filtered["visible_clues"]) >= 1
    discovered_ids = [c["clue_id"] for c in filtered["visible_clues"] if not c.get("hint_only")]
    assert "clue-1" in discovered_ids

    hidden_hint = [c for c in filtered["visible_clues"] if c.get("hint_only")]
    assert len(hidden_hint) == 0

    npc_names = [n["name"] for n in filtered["visible_npcs"]]
    assert "幕后黑手" not in npc_names


def test_standard_mode_shows_discovered_content(test_db):
    _setup_db(test_db)
    ctrl = SpoilerController(test_db)
    scenario = _make_scenario()

    filtered = ctrl.filter_for_player(scenario, "char-1", ["clue-1"], "standard")

    clue_ids = [c["clue_id"] for c in filtered["visible_clues"] if not c.get("hint_only")]
    assert "clue-1" in clue_ids

    hidden_hint = [c for c in filtered["visible_clues"] if c.get("hint_only")]
    assert len(hidden_hint) == 0

    npc_names = [n["name"] for n in filtered["visible_npcs"]]
    assert "管家" in npc_names


def test_cinematic_mode_shows_more(test_db):
    _setup_db(test_db)
    ctrl = SpoilerController(test_db)
    scenario = _make_scenario()

    filtered = ctrl.filter_for_player(scenario, "char-c", ["clue-1"], "cinematic")

    clue_ids = [c["clue_id"] for c in filtered["visible_clues"]]
    assert "clue-1" in clue_ids

    hidden_clues = [c for c in filtered["visible_clues"] if c.get("hint_only")]
    assert len(hidden_clues) >= 1

    npc_names = [n["name"] for n in filtered["visible_npcs"]]
    assert "幕后黑手" in npc_names
    hidden_npc = [n for n in filtered["visible_npcs"] if n.get("hidden")]
    assert len(hidden_npc) >= 1


def test_truth_never_revealed(test_db):
    _setup_db(test_db)
    ctrl = SpoilerController(test_db)
    scenario = _make_scenario()

    for level, char_id in [("strict", "char-1"), ("standard", "char-1"), ("cinematic", "char-c")]:
        filtered = ctrl.filter_for_player(scenario, char_id, ["clue-1"], level)
        filtered_str = json.dumps(filtered, ensure_ascii=False)
        assert "管家是凶手" not in filtered_str
        assert "truth_summary" not in filtered


def test_undiscovered_clues_hidden(test_db):
    _setup_db(test_db)
    ctrl = SpoilerController(test_db)
    scenario = _make_scenario()

    filtered = ctrl.filter_for_player(scenario, "char-1", [], "standard")

    clue_ids = [c["clue_id"] for c in filtered["visible_clues"] if not c.get("hint_only")]
    assert "clue-2" not in clue_ids


def test_strict_undiscovered_completely_hidden(test_db):
    _setup_db(test_db)
    ctrl = SpoilerController(test_db)
    scenario = _make_scenario()

    filtered = ctrl.filter_for_player(scenario, "char-1", [], "strict")

    clue_ids = [c["clue_id"] for c in filtered["visible_clues"]]
    assert "clue-2" not in clue_ids


def test_get_exposure_level(test_db):
    _setup_db(test_db)
    ctrl = SpoilerController(test_db)

    exposure = ctrl.get_exposure_level("room-1", "char-1")
    assert exposure["level"] == 1
    assert "clue-1" in exposure["discovered_elements"]


def test_get_exposure_no_clues(test_db):
    _setup_db(test_db)
    ctrl = SpoilerController(test_db)

    exposure = ctrl.get_exposure_level("room-1", "nonexistent")
    assert exposure["level"] == 0
    assert exposure["discovered_elements"] == []


def test_build_kp_context(test_db):
    _setup_db(test_db)
    ctrl = SpoilerController(test_db)
    scenario = _make_scenario()
    actions = [{"character_id": "char-1", "declared_intent": "查看走廊"}]

    context = ctrl.build_kp_context("room-1", scenario, actions)

    assert context["spoiler_level"] == "standard"
    assert len(context["character_contexts"]) == 1
    assert len(context["actions"]) == 1
    assert "truth_summary_for_kp_only" in context


def test_spoiler_level_visibility_tables():
    for level in ("strict", "standard", "cinematic"):
        vis = SPOILER_VISIBILITY[level]
        assert vis["ending"] == 0.0
        assert vis["public_observation"] == 1.0
