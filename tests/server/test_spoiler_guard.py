"""Tests for SpoilerGuard — anti-spoiler output interception."""

import json
import pytest
from src.server.engine.spoiler_guard import SpoilerGuard, SAFE_FALLBACK_TEMPLATES
from src.server.models import (
    SpoilerSensitiveItem, SpoilerReviewResult, SpoilerUnlockState,
)


# ── Test Knowledge Graphs ──

def _make_kg_with_hidden():
    """Knowledge graph with hidden NPCs, clues, truth, and endings."""
    return {
        "scenes": [
            {"name": "庄园大厅", "description": "昏暗的大厅，烛光摇曳", "order": 1},
            {"name": "地下室", "description": "潮湿阴暗的地下室", "order": 2},
        ],
        "npcs": [
            {"name": "管家老王", "role": "管家", "description": "看似忠厚老实", "is_hidden": False},
            {"name": "张教授", "role": "幕后真凶", "description": "表面是大学教授，实为邪教头目", "is_hidden": True,
             "public_description": "一个神秘的身影"},
        ],
        "clues": [
            {"name": "血迹", "description": "地板上的暗红色血迹", "is_hidden": False, "location": "庄园大厅"},
            {"name": "地下室的尸体", "description": "地下室内发现的一具无名尸体", "is_hidden": True, "location": "地下室"},
            {"name": "祭坛铭文", "description": "墙上刻着的诡异符号", "is_hidden": True,
             "clue_id": "clue-secret-1"},
        ],
        "truth": {"summary": "张教授为了复活亡妻，用邪教仪式杀害了三名村民"},
        "truth_summary": "真相：张教授是邪教头目，杀害村民进行复活仪式。",
        "endings": [
            {"name": "真结局", "description": "揭露张教授的真面目，阻止仪式", "type": "victory"},
            {"name": "坏结局", "description": "张教授成功完成仪式", "type": "defeat"},
        ],
    }


def _make_kg_clean():
    """Knowledge graph with no hidden content."""
    return {
        "scenes": [{"name": "公园", "description": "阳光明媚的公园", "order": 1}],
        "npcs": [{"name": "路人甲", "role": "路人", "description": "普通行人", "is_hidden": False}],
        "clues": [{"name": "脚印", "description": "泥土上的新鲜脚印", "is_hidden": False}],
        "truth": None,
        "endings": [],
    }


# ── Tests: Index Building ──

class TestBuildSensitiveIndex:
    def test_build_index_from_kg(self, test_db):
        sg = SpoilerGuard(test_db)
        kg = _make_kg_with_hidden()
        items = sg.build_sensitive_index("sc-test", kg)

        categories = [i.category for i in items]
        assert "truth" in categories, "Truth should be extracted"
        assert "ending" in categories, "Endings should be extracted"
        assert "hidden_clue" in categories, "Hidden clues should be extracted"
        assert "hidden_npc" in categories, "Hidden NPCs should be extracted"

        # Verify hidden NPC
        npc_item = next((i for i in items if i.category == "hidden_npc"), None)
        assert npc_item is not None
        assert npc_item.label == "张教授"
        assert npc_item.default_audience == "host"

        # Verify hidden clue count
        hidden_clues = [i for i in items if i.category == "hidden_clue"]
        assert len(hidden_clues) >= 2

    def test_build_index_empty_kg(self, test_db):
        sg = SpoilerGuard(test_db)
        items = sg.build_sensitive_index("sc-empty", {})
        assert items == []

    def test_build_index_no_hidden(self, test_db):
        sg = SpoilerGuard(test_db)
        kg = _make_kg_clean()
        items = sg.build_sensitive_index("sc-clean", kg)
        # Only public NPCs and clues — no hidden items
        hidden = [i for i in items if i.category in ("hidden_clue", "hidden_npc", "truth", "ending")]
        assert len(hidden) == 0

    def test_confirmed_boundary_releases_only_after_its_unlock_clue(self, test_db):
        sg = SpoilerGuard(test_db)
        kg = _make_kg_with_hidden()
        kg["spoiler_boundaries"] = [{
            "id": "truth",
            "target_type": "truth",
            "target_id": "truth",
            "player_visibility": "discovered",
            "host_visibility": "complete",
            "player_description": "调查背后另有隐情。",
            "unlock_clues": ["clue-secret-1"],
            "citation": {"source_part_id": "part-1"},
        }, {
            "id": "npc:1",
            "target_type": "npc",
            "target_id": "1",
            "player_visibility": "discovered",
            "host_visibility": "complete",
            "player_description": "一个神秘的身影。",
            "unlock_clues": ["clue-secret-1"],
            "citation": {"source_part_id": "part-1"},
        }]

        index = sg.build_sensitive_index("sc-boundary", kg)
        truth = next(item for item in index if item.category == "truth")
        blocked = sg.review(
            "张教授为了复活亡妻，用邪教仪式杀害了三名村民。",
            "party",
            None,
            SpoilerUnlockState(roomId="room-boundary"),
            index,
        )
        released = sg.review(
            "张教授为了复活亡妻，用邪教仪式杀害了三名村民。",
            "party",
            None,
            SpoilerUnlockState(roomId="room-boundary", discoveredClueIds=["clue-secret-1"]),
            index,
        )

        assert truth.unlock_clue_ids == ["clue-secret-1"]
        assert blocked.allowed is False
        assert released.allowed is True

    def test_persist_and_load_index(self, test_db):
        sg = SpoilerGuard(test_db)
        kg = _make_kg_with_hidden()
        items = sg.build_sensitive_index("sc-persist", kg)
        assert len(items) > 0

        loaded = sg.load_index("sc-persist")
        assert len(loaded) == len(items)
        assert {item.item_id for item in loaded} == {item.item_id for item in items}

    def test_rebuild_index(self, test_db):
        # Insert a scenario first
        kg = _make_kg_with_hidden()
        test_db.execute(
            "INSERT INTO scenarios (scenario_id, title, knowledge_graph) VALUES (%s, %s, %s)",
            ("sc-rebuild", "Test Scenario", json.dumps(kg, ensure_ascii=False)),
        )
        test_db.commit()

        sg = SpoilerGuard(test_db)
        count = sg.rebuild_index("sc-rebuild")
        assert count > 0

        loaded = sg.load_index("sc-rebuild")
        assert len(loaded) == count


# ── Tests: Review ──

class TestReview:
    @pytest.fixture
    def sg(self, test_db):
        return SpoilerGuard(test_db)

    @pytest.fixture
    def index(self, test_db):
        sg = SpoilerGuard(test_db)
        kg = _make_kg_with_hidden()
        return sg.build_sensitive_index("sc-review", kg)

    @pytest.fixture
    def unlock(self):
        return SpoilerUnlockState(roomId="room-review")

    def test_review_clean_text(self, sg, index, unlock):
        """Clean text with no sensitive references should pass."""
        text = "你走进庄园大厅，看到墙上的旧照片和落满灰尘的家具。"
        result = sg.review(text, "party", None, unlock, index)
        assert result.allowed is True
        assert len(result.violations) == 0

    def test_review_spoiler_truth(self, sg, index, unlock):
        """Text containing truth summary should be flagged."""
        text = "根据线索分析，张教授为了复活亡妻，用邪教仪式杀害了三名村民。"
        result = sg.review(text, "party", None, unlock, index)
        assert result.allowed is False
        assert len(result.violations) > 0
        # At least one violation from truth category
        truth_violations = [v for v in result.violations if v["category"] == "truth"]
        assert len(truth_violations) > 0

    def test_review_spoiler_hidden_npc(self, sg, index, unlock):
        """Text mentioning hidden NPC should be flagged."""
        text = "你们发现张教授才是幕后黑手。"
        result = sg.review(text, "party", None, unlock, index)
        assert result.allowed is False
        npc_violations = [v for v in result.violations if v["category"] == "hidden_npc"]
        assert len(npc_violations) > 0

    def test_review_spoiler_hidden_clue(self, sg, index, unlock):
        """Text mentioning hidden clue should be flagged."""
        text = "你发现了地下室内的一具无名尸体，墙上刻着的诡异符号令人不安。"
        result = sg.review(text, "party", None, unlock, index)
        assert result.allowed is False
        clue_violations = [v for v in result.violations if v["category"] == "hidden_clue"]
        assert len(clue_violations) > 0

    def test_review_host_audience_bypass(self, sg, index, unlock):
        """Sensitive item with default_audience='host' should pass when audience='host'."""
        text = "真相：张教授是邪教头目，杀害村民进行复活仪式。"
        result = sg.review(text, "host", None, unlock, index)
        assert result.allowed is True, "Host should see all content"

    def test_review_party_blocks_host_item(self, sg, index, unlock):
        """Same text should be BLOCKED when audience is 'party'."""
        text = "真相：张教授是邪教头目，杀害村民进行复活仪式。"
        result = sg.review(text, "party", None, unlock, index)
        assert result.allowed is False, "Party should NOT see host-only content"

    def test_review_empty_text(self, sg, index, unlock):
        result = sg.review("", "party", None, unlock, index)
        assert result.allowed is True

    def test_review_empty_index(self, sg, unlock):
        result = sg.review("张教授是凶手", "party", None, unlock, [])
        assert result.allowed is True


# ── Tests: Retry Prompt & Fallback ──

class TestRetryAndFallback:
    def test_generate_retry_prompt(self, test_db):
        sg = SpoilerGuard(test_db)
        violations = [
            {"item_id": "sc:truth:0", "category": "truth", "label": "真相摘要", "matched_text": "凶手是管家", "source_ref": "kg.truth.summary"},
            {"item_id": "sc:npc:1", "category": "hidden_npc", "label": "张教授", "matched_text": "张教授", "source_ref": "kg.npcs[1]"},
        ]
        prompt = sg.generate_retry_prompt(violations)
        assert "真相" in prompt
        assert "隐藏NPC" in prompt
        assert "张教授" in prompt
        assert "请仅使用已公开的信息" in prompt

    def test_get_safe_fallback(self, test_db):
        sg = SpoilerGuard(test_db)
        for hint in ("general", "investigation", "dialogue", "combat", "move"):
            text = sg.get_safe_fallback(hint)
            assert text, f"Fallback for '{hint}' should not be empty"
            assert len(text) > 5

    def test_get_safe_fallback_unknown_hint(self, test_db):
        sg = SpoilerGuard(test_db)
        text = sg.get_safe_fallback("nonexistent")
        assert text == SAFE_FALLBACK_TEMPLATES["general"]

    def test_retry_prompt_included_in_result(self, test_db):
        sg = SpoilerGuard(test_db)
        kg = _make_kg_with_hidden()
        index = sg.build_sensitive_index("sc-retry-prompt", kg)
        unlock = SpoilerUnlockState(roomId="room-retry")
        text = "张教授是邪教头目，他杀害了三名村民。"
        result = sg.review(text, "party", None, unlock, index)
        assert not result.allowed
        assert result.retry_prompt
        assert result.safe_fallback_text


# ── Tests: Unlock State ──

class TestUnlockState:
    def test_compute_unlock_state_empty(self, test_db):
        sg = SpoilerGuard(test_db)
        state = sg.compute_unlock_state("room-nonexistent")
        assert state.room_id == "room-nonexistent"
        assert state.discovered_clue_ids == []

    def test_compute_unlock_state_with_clues(self, test_db):
        # Setup: create room + clues
        test_db.execute(
            "INSERT INTO rooms (room_id, owner_token) VALUES ('room-clues', 't1')"
        )
        test_db.execute(
            "INSERT INTO clues (clue_id, room_id, character_id, text) VALUES ('c1', 'room-clues', 'ch1', 'test clue')"
        )
        test_db.execute(
            "INSERT INTO clues (clue_id, room_id, character_id, text) VALUES ('c2', 'room-clues', 'ch1', 'test clue 2')"
        )
        test_db.commit()

        sg = SpoilerGuard(test_db)
        state = sg.compute_unlock_state("room-clues")
        assert "c1" in state.discovered_clue_ids
        assert "c2" in state.discovered_clue_ids

    def test_unlocked_clue_not_flagged(self, test_db):
        """A hidden clue that's been discovered should NOT be flagged."""
        sg = SpoilerGuard(test_db)
        kg = _make_kg_with_hidden()
        index = sg.build_sensitive_index("sc-unlocked", kg)

        # Setup room with the hidden clue "祭坛铭文" (clue_id="clue-secret-1") discovered
        test_db.execute(
            "INSERT INTO rooms (room_id, owner_token) VALUES ('room-unlocked', 't1')"
        )
        test_db.execute(
            "INSERT INTO clues (clue_id, room_id, character_id, text) VALUES ('clue-secret-1', 'room-unlocked', 'ch1', 'hidden clue')"
        )
        test_db.commit()

        unlock = sg.compute_unlock_state("room-unlocked")
        assert "clue-secret-1" in unlock.discovered_clue_ids

        # This text mentions the description of clue clue-secret-1, but it's unlocked
        text = "墙上刻着的诡异符号似乎在指引什么方向。"
        result = sg.review(text, "party", None, unlock, index)
        # Only check clues specifically tied to clue-secret-1
        clue_violations = [
            v for v in result.violations
            if v["category"] == "hidden_clue" and "clue-secret-1" in v.get("item_id", "")
        ]
        assert len(clue_violations) == 0, "Unlocked clue 'clue-secret-1' should not be flagged"

        # But other hidden clues (like "地下室的无名尸体") should still be flagged
        other_violations = [
            v for v in result.violations
            if v["category"] == "hidden_clue" and "clue-secret-1" not in v.get("item_id", "")
        ]
        # May or may not have other violations depending on text overlap
        # The unlocked clue specifically should not appear
        assert all("clue-secret-1" not in v.get("item_id", "") for v in result.violations), \
            "Unlocked clue should not appear in violations"


# ── Tests: Audit Logging ──

class TestAuditLogging:
    def test_log_audit(self, test_db):
        sg = SpoilerGuard(test_db)
        test_db.execute(
            "INSERT INTO rooms (room_id, owner_token) VALUES ('room-audit', 't1')"
        )
        test_db.commit()

        audit_id = sg.log_audit(
            "room-audit", "action-1", "original spoiler text",
            [{"category": "truth", "label": "真相"}],
            1, "retry_ok", "safe retry text",
        )
        assert audit_id
        assert len(audit_id) == 12

        # Verify persisted
        row = test_db.execute(
            "SELECT * FROM spoiler_audits WHERE audit_id = %s", (audit_id,)
        ).fetchone()
        assert row is not None
        assert row["room_id"] == "room-audit"
        assert row["final_status"] == "retry_ok"
        assert row["retry_count"] == 1


# ── Tests: Alias Extraction ──

class TestAliasExtraction:
    def test_extract_quoted_names(self):
        aliases = SpoilerGuard._extract_aliases('他被称为「血手印」，外号"教授杀手"。', "npc")
        assert len(aliases) >= 2

    def test_extract_parenthetical(self):
        aliases = SpoilerGuard._extract_aliases("张教授（真名：张伟强），是一名（邪教头目）。", "npc")
        # Should find at least "张伟强" and "邪教头目"
        assert any("张伟强" in a for a in aliases) or any("邪教头目" in a for a in aliases)

    def test_extract_empty_text(self):
        aliases = SpoilerGuard._extract_aliases("", "npc")
        assert aliases == []


# ── Tests: Audience Logic ──

class TestAudienceLogic:
    def test_host_to_host_allowed(self):
        assert SpoilerGuard._audience_allows_static("host", "host") is True

    def test_host_to_party_blocked(self):
        assert SpoilerGuard._audience_allows_static("host", "party") is False

    def test_host_to_player_blocked(self):
        assert SpoilerGuard._audience_allows_static("host", "player") is False

    def test_party_to_all_allowed(self):
        assert SpoilerGuard._audience_allows_static("party", "host") is True
        assert SpoilerGuard._audience_allows_static("party", "player") is True
        assert SpoilerGuard._audience_allows_static("party", "party") is True
