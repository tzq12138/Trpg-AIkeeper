import pytest


def test_join_rate_limit_uses_account_bucket_for_authenticated_players():
    from src.server.player.router_player import _join_attempts, _join_rate_key, _check_rate_limit

    _join_attempts.clear()
    for index in range(8):
        _check_rate_limit(_join_rate_key("127.0.0.1", {"account_id": f"player-{index}"}))

    anonymous_key = _join_rate_key("127.0.0.1", None)
    for _ in range(5):
        _check_rate_limit(anonymous_key)
    with pytest.raises(Exception) as exc_info:
        _check_rate_limit(anonymous_key)
    assert getattr(exc_info.value, "status_code", None) == 429
