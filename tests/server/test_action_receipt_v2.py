import pytest

from src.server.engine.roll_receipt import create_roll_receipt, verify_roll_receipt
from src.server.engine.secure_random import secure_randint
from src.server.engine.skill_check import roll_skill_check
from src.server.rules.coc_handlers import roll_dice


class _FixedRng:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def randint(self, _low, _high):
        self.calls += 1
        return self.value


class _SequenceRng:
    def __init__(self, values):
        self.values = iter(values)

    def randint(self, _low, _high):
        return next(self.values)


def test_secure_randint_uses_system_rng_outside_dev_mode(monkeypatch):
    system_rng = _FixedRng(73)
    legacy_rng = _FixedRng(12)
    monkeypatch.setenv("AIKEEPER_DEV_MODE", "0")
    monkeypatch.setattr("src.server.engine.secure_random._system_rng", system_rng)

    assert secure_randint(1, 100, test_rng=legacy_rng) == 73
    assert system_rng.calls == 1
    assert legacy_rng.calls == 0


def test_secure_randint_keeps_deterministic_test_injection_in_dev_mode(monkeypatch):
    system_rng = _FixedRng(73)
    legacy_rng = _FixedRng(12)
    monkeypatch.setenv("AIKEEPER_DEV_MODE", "1")
    monkeypatch.setattr("src.server.engine.secure_random._system_rng", system_rng)

    assert secure_randint(1, 100, test_rng=legacy_rng) == 12
    assert legacy_rng.calls == 1
    assert system_rng.calls == 0


def test_skill_check_uses_secure_rng_outside_dev_mode(monkeypatch):
    monkeypatch.setenv("AIKEEPER_DEV_MODE", "0")
    monkeypatch.setattr(
        "src.server.engine.secure_random._system_rng",
        _SequenceRng([4, 2]),
    )
    monkeypatch.setattr(
        "src.server.engine.skill_check.random.randint",
        lambda _low, _high: (_ for _ in ()).throw(AssertionError("legacy RNG used")),
    )

    result = roll_skill_check(60)

    assert result["roll"] == 42
    assert result["roll_trace"]["tens"] == [4]


def test_damage_dice_use_secure_rng_outside_dev_mode(monkeypatch):
    monkeypatch.setenv("AIKEEPER_DEV_MODE", "0")
    monkeypatch.setattr(
        "src.server.engine.secure_random._system_rng",
        _SequenceRng([3, 4]),
    )
    monkeypatch.setattr(
        "src.server.rules.coc_handlers.random.randint",
        lambda _low, _high: (_ for _ in ()).throw(AssertionError("legacy RNG used")),
    )

    total, draws, modifier = roll_dice("2d6")

    assert (total, draws, modifier) == (7, [3, 4], 0)


def test_roll_receipt_binds_action_ruleset_timestamp_and_raw_rolls():
    receipt = create_roll_receipt(
        action_id="action-1",
        rule_set_version="coc7-v1",
        rolled_at="2026-07-11T10:00:00+00:00",
        raw_rolls=[{"dice": "d100", "values": [4, 2], "result": 42}],
        secret="test-secret",
    )

    assert receipt["action_id"] == "action-1"
    assert receipt["rule_set_version"] == "coc7-v1"
    assert receipt["rolled_at"] == "2026-07-11T10:00:00+00:00"
    assert verify_roll_receipt(receipt, secret="test-secret") is True


def test_roll_receipt_rejects_tampered_raw_rolls():
    receipt = create_roll_receipt(
        action_id="action-1",
        rule_set_version="coc7-v1",
        rolled_at="2026-07-11T10:00:00+00:00",
        raw_rolls=[{"dice": "d100", "values": [4, 2], "result": 42}],
        secret="test-secret",
    )
    receipt["raw_rolls"][0]["result"] = 1

    assert verify_roll_receipt(receipt, secret="test-secret") is False


def test_roll_receipt_uses_isolated_development_secret_in_dev_mode(monkeypatch):
    monkeypatch.delenv("ROLL_RECEIPT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("AIKEEPER_DEV_MODE", "1")

    receipt = create_roll_receipt(
        action_id="dev-action",
        rule_set_version="coc7-dev",
        rolled_at="2026-07-12T00:00:00Z",
        raw_rolls=[{"kind": "d100", "value": 42}],
    )

    assert verify_roll_receipt(receipt) is True


def test_roll_receipt_still_requires_secret_outside_dev_mode(monkeypatch):
    monkeypatch.delenv("ROLL_RECEIPT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("AIKEEPER_DEV_MODE", raising=False)

    with pytest.raises(RuntimeError, match="ROLL_RECEIPT_SECRET or JWT_SECRET is required"):
        create_roll_receipt(
            action_id="prod-action",
            rule_set_version="coc7",
            rolled_at="2026-07-12T00:00:00Z",
            raw_rolls=[{"kind": "d100", "value": 42}],
        )
