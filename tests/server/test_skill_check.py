import pytest
from src.server.skill_check import roll_skill_check, _compute_threshold, _determine_success


class TestComputeThreshold:
    def test_regular(self):
        assert _compute_threshold(60, "regular") == 60

    def test_hard(self):
        assert _compute_threshold(60, "hard") == 30

    def test_extreme(self):
        assert _compute_threshold(60, "extreme") == 12

    def test_odd_value_hard(self):
        assert _compute_threshold(55, "hard") == 27

    def test_odd_value_extreme(self):
        assert _compute_threshold(55, "extreme") == 11


class TestDetermineSuccess:
    def test_critical_on_1(self):
        assert _determine_success(1, 60, 60) == "critical"

    def test_fumble_on_100(self):
        assert _determine_success(100, 60, 60) == "fumble"

    def test_extreme(self):
        assert _determine_success(5, 60, 60) == "extreme"

    def test_hard(self):
        assert _determine_success(20, 60, 60) == "hard"

    def test_regular(self):
        assert _determine_success(50, 60, 60) == "regular"

    def test_failure(self):
        assert _determine_success(80, 60, 60) == "failure"

    def test_critical_takes_precedence_over_extreme(self):
        assert _determine_success(1, 100, 100) == "critical"

    def test_fumble_takes_precedence(self):
        assert _determine_success(100, 100, 100) == "fumble"


class TestRollSkillCheck:
    def test_returns_all_fields(self):
        result = roll_skill_check(60)
        assert "skill_value" in result
        assert "roll" in result
        assert "difficulty" in result
        assert "success_level" in result
        assert "detail" in result

    def test_roll_in_range(self):
        for _ in range(100):
            result = roll_skill_check(50)
            assert 1 <= result["roll"] <= 100

    def test_difficulty_passed_through(self):
        result = roll_skill_check(60, difficulty="hard")
        assert result["difficulty"] == "hard"

    def test_bonus_dice_positive(self):
        result = roll_skill_check(60, bonus_dice=2)
        assert 1 <= result["roll"] <= 100

    def test_penalty_dice_negative(self):
        result = roll_skill_check(60, bonus_dice=-1)
        assert 1 <= result["roll"] <= 100

    def test_success_levels_are_valid(self):
        valid = {"critical", "extreme", "hard", "regular", "failure", "fumble"}
        for _ in range(200):
            result = roll_skill_check(60, bonus_dice=1)
            assert result["success_level"] in valid

    def test_skill_value_0_always_fails_except_critical(self):
        failures = 0
        for _ in range(100):
            result = roll_skill_check(0)
            if result["roll"] not in (1, 100):
                assert result["success_level"] == "failure"
                failures += 1
        assert failures > 50

    def test_skill_value_100_can_succeed(self):
        successes = 0
        for _ in range(100):
            result = roll_skill_check(100)
            if result["success_level"] != "fumble":
                successes += 1
        assert successes > 50
