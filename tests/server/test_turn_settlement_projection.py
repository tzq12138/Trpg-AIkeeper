from src.server.player.router_player import build_turn_resolved_projection


def test_turn_projection_never_broadcasts_raw_actions_or_resolution_results():
    payload = build_turn_resolved_projection(
        "turn-1",
        [
            {
                "action_id": "action-1",
                "character_name": "艾莉丝",
                "declared_intent": "我偷偷把钥匙藏起来。",
                "result": {"mutations": [{"path": "/inventory", "value": "钥匙"}]},
            },
        ],
    )

    assert payload == {
        "turnId": "turn-1",
        "actionCount": 1,
        "summary": "本回合行动已分别结算；请查看最新场景叙事后继续描述行动。",
    }
    assert "declared_intent" not in payload
    assert "mutations" not in str(payload)
