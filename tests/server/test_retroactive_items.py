import pytest

from src.server.models import PlayerIntent
from src.server.retro_items import (
    RetroactiveClaimError,
    RetroactiveItemService,
    extract_retroactive_claim,
)


def doctor_character():
    return {
        "character_id": "char-1",
        "room_id": "room-1",
        "xlsx_data": {
            "occupation": "doctor",
            "luck": 60,
            "skills": {"知识": 50},
        },
    }


def scenario_assets():
    return {
        "items": {
            "gloves": {
                "itemId": "gloves",
                "name": "医用塑胶手套",
                "narrative": {
                    "tags": ["医疗", "防护", "无害"],
                    "baselineAccess": "common_professional",
                    "description": "普通手套",
                },
            },
            "scalpel": {
                "itemId": "scalpel",
                "name": "锋利手术刀",
                "narrative": {
                    "tags": ["医疗", "危险"],
                    "baselineAccess": "restricted",
                    "description": "锋利器械",
                },
            },
            "ritual_key": {
                "itemId": "ritual_key",
                "name": "仪式钥匙",
                "narrative": {
                    "tags": ["剧情"],
                    "baselineAccess": "unique",
                },
            },
        },
        "professionsMatrix": {
            "doctor": {
                "tags": ["医疗", "救助"],
                "allowedAccessLevels": ["common", "common_professional", "restricted"],
            },
            "drifter": {
                "tags": ["流浪", "街头"],
                "allowedAccessLevels": ["common"],
            },
        },
    }


def test_extract_retroactive_claim_from_natural_language():
    claim = extract_retroactive_claim("我从包里拿出医用塑胶手套")

    assert claim is not None
    assert claim["claimedItemName"] == "医用塑胶手套"
    assert claim["justificationText"] == "我从包里拿出医用塑胶手套"


def test_evaluate_auto_pass_for_professional_common_item():
    service = RetroactiveItemService(conn=None)
    intent = PlayerIntent(
        intent_type="retroactive_item_claim",
        declared_intent="医生常备手套",
        params={"claimedItemName": "医用塑胶手套", "justificationText": "我是医生"},
    )

    decision = service.evaluate_claim(intent, doctor_character(), scenario_assets())

    assert decision.branch == "auto_pass"
    assert decision.item["name"] == "医用塑胶手套"


def test_evaluate_restricted_related_item_requires_roll():
    service = RetroactiveItemService(conn=None)
    intent = PlayerIntent(
        intent_type="retroactive_item_claim",
        params={"claimedItemName": "锋利手术刀", "justificationText": "医生可能有"},
    )

    decision = service.evaluate_claim(intent, doctor_character(), scenario_assets())

    assert decision.branch == "roll_required"
    assert decision.roll_skill in {"luck", "know"}


def test_evaluate_unique_item_is_forbidden():
    service = RetroactiveItemService(conn=None)
    intent = PlayerIntent(
        intent_type="retroactive_item_claim",
        params={"claimedItemName": "仪式钥匙", "justificationText": "我想要"},
    )

    with pytest.raises(RetroactiveClaimError) as exc:
        service.evaluate_claim(intent, doctor_character(), scenario_assets())

    assert exc.value.status_code == 403


def test_evaluate_unrelated_profession_is_refused():
    service = RetroactiveItemService(conn=None)
    char = doctor_character()
    char["xlsx_data"]["occupation"] = "drifter"
    intent = PlayerIntent(
        intent_type="retroactive_item_claim",
        params={"claimedItemName": "锋利手术刀", "justificationText": "路上捡的"},
    )

    with pytest.raises(RetroactiveClaimError) as exc:
        service.evaluate_claim(intent, char, scenario_assets())

    assert exc.value.status_code == 409
