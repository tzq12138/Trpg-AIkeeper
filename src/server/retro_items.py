import json
import re
from dataclasses import dataclass
from typing import Any

from .models import PlayerIntent


CLAIM_RE = re.compile(
    r"(?:我(?:有|带了|携带)|(?:从[^，。,.]*里)?(?:拿出|掏出|取出))(?P<item>[\u4e00-\u9fa5A-Za-z0-9 _-]{1,24})"
)


class RetroactiveClaimError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class RetroactiveClaimDecision:
    branch: str
    item: dict[str, Any]
    claimed_item_name: str
    justification_text: str
    roll_skill: str | None = None


def extract_retroactive_claim(text: str) -> dict[str, str] | None:
    match = CLAIM_RE.search(text or "")
    if not match:
        return None
    item = match.group("item").strip(" ，。,.")
    if not item:
        return None
    return {"claimedItemName": item, "justificationText": text}


class RetroactiveItemService:
    def __init__(self, conn):
        self.conn = conn

    def evaluate_claim(
        self,
        intent: PlayerIntent,
        character: dict[str, Any],
        scenario_assets: dict[str, Any] | None,
    ) -> RetroactiveClaimDecision:
        params = intent.params or {}
        natural_claim = extract_retroactive_claim(intent.declared_intent)
        claimed_name = (
            params.get("claimedItemName")
            or params.get("claimed_item_name")
            or (natural_claim or {}).get("claimedItemName")
            or ""
        ).strip()
        justification = (
            params.get("justificationText")
            or params.get("justification_text")
            or (natural_claim or {}).get("justificationText")
            or intent.declared_intent
            or ""
        )
        if not claimed_name:
            raise RetroactiveClaimError(400, "claimedItemName is required")

        assets = scenario_assets or {}
        item = self._find_item(assets, claimed_name)
        if not item:
            return RetroactiveClaimDecision(
                branch="roll_required",
                item={
                    "itemId": self._slug(claimed_name),
                    "name": claimed_name,
                    "narrative": {
                        "tags": [],
                        "baselineAccess": "restricted",
                        "description": "",
                    },
                },
                claimed_item_name=claimed_name,
                justification_text=justification,
                roll_skill="luck",
            )

        narrative = item.get("narrative", {})
        baseline = narrative.get("baselineAccess", "restricted")
        if baseline == "unique":
            raise RetroactiveClaimError(403, "Unique scenario item cannot be claimed")

        profession_key, profession = self._profession(character, assets)
        profession_tags = set(profession.get("tags", []))
        item_tags = set(narrative.get("tags", []))
        allowed_levels = set(profession.get("allowedAccessLevels", ["common"]))
        tag_overlap = bool(profession_tags & item_tags)

        if baseline in {"common", "common_professional"} and (
            baseline == "common" or (baseline in allowed_levels and tag_overlap)
        ):
            return RetroactiveClaimDecision(
                branch="auto_pass",
                item=item,
                claimed_item_name=claimed_name,
                justification_text=justification,
            )

        if baseline == "restricted" and tag_overlap and baseline in allowed_levels:
            return RetroactiveClaimDecision(
                branch="roll_required",
                item=item,
                claimed_item_name=claimed_name,
                justification_text=justification,
                roll_skill="luck" if profession_key != "scholar" else "know",
            )

        raise RetroactiveClaimError(409, "Claim does not fit character background")

    def _find_item(self, assets: dict[str, Any], claimed_name: str) -> dict[str, Any] | None:
        for item_id, item in (assets.get("items") or {}).items():
            name = item.get("name", "")
            if name == claimed_name or claimed_name in name or name in claimed_name:
                normalized = dict(item)
                normalized.setdefault("itemId", item.get("itemId") or item_id)
                return normalized
        return None

    def _profession(self, character: dict[str, Any], assets: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        xlsx_data = character.get("xlsx_data") or {}
        if isinstance(xlsx_data, str):
            try:
                xlsx_data = json.loads(xlsx_data)
            except json.JSONDecodeError:
                xlsx_data = {}
        occupation = str(
            xlsx_data.get("occupation")
            or xlsx_data.get("职业")
            or character.get("occupation")
            or ""
        ).lower()
        matrix = assets.get("professionsMatrix") or assets.get("professions_matrix") or {}
        if occupation in matrix:
            return occupation, matrix[occupation]
        for key, profile in matrix.items():
            if key.lower() in occupation or occupation in key.lower():
                return key, profile
        return occupation or "unknown", {"tags": [], "allowedAccessLevels": ["common"]}

    def _slug(self, name: str) -> str:
        cleaned = re.sub(r"\W+", "_", name, flags=re.UNICODE).strip("_")
        return f"claim_{cleaned or 'item'}"
