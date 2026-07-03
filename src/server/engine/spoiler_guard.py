"""SpoilerGuard — anti-spoiler output interception for AI-Keeper TRPG.

Public output is checked against a structured sensitive-item index.
Violations trigger a single retry; a second violation falls back to safe template text.
All intercepts are audit-logged (admin-only).
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from ..models import (
    SpoilerSensitiveItem,
    SpoilerReviewResult,
    SpoilerUnlockState,
    SpoilerAuditEntry,
)

logger = logging.getLogger(__name__)

SAFE_FALLBACK_TEMPLATES: dict[str, str] = {
    "general": "空气中的线索仍然模糊，调查需要更具体的行动才能推进。",
    "investigation": "你仔细查看了周围，但目前没有发现更多可以直接确认的信息。需要换个角度再试试。",
    "dialogue": "对方的回答含糊其辞，似乎有些事情还不能现在就说清楚。",
    "combat": "战斗的混乱中，细节变得模糊。先专注于眼前的威胁。",
    "move": "你到达了目的地，但前方的景象还需要进一步探索才能明了。",
}


class SpoilerGuard:
    """Output-side anti-spoiler gate.

    Architecture:
    1. build_sensitive_index() — extract sensitive items from knowledge_graph
    2. compute_unlock_state() — aggregate unlock evidence from event log + DB
    3. review() — deterministic text match against un-unlocked sensitive items
    4. generate_retry_prompt() — build Chinese constraint prompt for AI retry
    5. get_safe_fallback() — template safe narrative
    """

    def __init__(self, conn):
        self.conn = conn

    # ── Index Building ──────────────────────────────────────────────

    def build_sensitive_index(
        self,
        scenario_id: str,
        knowledge_graph: dict,
        assets: dict | None = None,
    ) -> list[SpoilerSensitiveItem]:
        """Extract all sensitive items from a scenario's knowledge_graph + assets.

        Sources:
        - truth.summary → category "truth"
        - endings[*].name + description → category "ending"
        - clues[*] where is_hidden == true → category "hidden_clue"
        - npcs[*] where is_hidden == true → category "hidden_npc"
        - assets items where is_secret == true → category "hidden_asset"
        """
        items: list[SpoilerSensitiveItem] = []
        if not knowledge_graph:
            return items

        # Truth
        truth = knowledge_graph.get("truth") or {}
        truth_summary = truth.get("summary", "") or knowledge_graph.get("truth_summary", "")
        if truth_summary:
            aliases = self._extract_aliases(truth_summary, "truth")
            # Also include key substrings from the truth summary itself
            aliases = self._add_key_phrases(truth_summary, aliases)
            items.append(SpoilerSensitiveItem(
                itemId=f"{scenario_id}:truth:summary",
                scenarioId=scenario_id,
                category="truth",
                label="真相摘要",
                aliases=aliases,
                sourceRef="knowledge_graph.truth.summary",
                defaultAudience="host",
            ))

        # Endings
        for i, ending in enumerate(knowledge_graph.get("endings", []) or []):
            name = ending.get("name", "")
            desc = ending.get("description", "")
            label = name or f"结局{i + 1}"
            text_parts = [name, desc] if name and desc else [name or desc]
            aliases = self._extract_aliases(" ".join(text_parts), "ending")
            items.append(SpoilerSensitiveItem(
                itemId=f"{scenario_id}:ending:{i}",
                scenarioId=scenario_id,
                category="ending",
                label=label,
                aliases=aliases,
                sourceRef=f"knowledge_graph.endings[{i}]",
                defaultAudience="host",
            ))

        # Hidden clues
        for i, clue in enumerate(knowledge_graph.get("clues", []) or []):
            if clue.get("is_hidden"):
                name = clue.get("name", "")
                desc = clue.get("description", "")
                clue_id = clue.get("clue_id", "")
                label = name or desc or f"隐藏线索{i + 1}"
                text_parts = [name, desc] if name and desc else [name or desc]
                aliases = self._extract_aliases(" ".join(text_parts), "clue")
                aliases = self._add_key_phrases(desc, aliases)
                source_ref = f"clue_id:{clue_id}" if clue_id else f"knowledge_graph.clues[{i}]"
                items.append(SpoilerSensitiveItem(
                    itemId=f"{scenario_id}:hidden_clue:{clue_id}" if clue_id else f"{scenario_id}:hidden_clue:{i}",
                    scenarioId=scenario_id,
                    category="hidden_clue",
                    label=label,
                    aliases=aliases,
                    sourceRef=source_ref,
                    defaultAudience="host",
                ))

        # Hidden NPCs
        for i, npc in enumerate(knowledge_graph.get("npcs", []) or []):
            if npc.get("is_hidden"):
                name = npc.get("name", "")
                desc = npc.get("description", "")
                role = npc.get("role", "")
                label = name or f"隐藏NPC{i + 1}"
                text_parts = [name, role, desc]
                aliases = self._extract_aliases(" ".join([p for p in text_parts if p]), "npc")
                items.append(SpoilerSensitiveItem(
                    itemId=f"{scenario_id}:hidden_npc:{i}",
                    scenarioId=scenario_id,
                    category="hidden_npc",
                    label=label,
                    aliases=aliases,
                    sourceRef=f"knowledge_graph.npcs[{i}]",
                    defaultAudience="host",
                ))

        # Hidden assets (from scenario_assets JSONB)
        if assets:
            asset_items = assets.get("items", {}) if isinstance(assets, dict) else {}
            for key, asset in asset_items.items():
                if isinstance(asset, dict) and asset.get("is_secret"):
                    name = asset.get("name", key)
                    desc = asset.get("description", "") or asset.get("narrative", {}).get("description", "")
                    aliases = self._extract_aliases(f"{name} {desc}", "asset")
                    items.append(SpoilerSensitiveItem(
                        itemId=f"{scenario_id}:hidden_asset:{key}",
                        scenarioId=scenario_id,
                        category="hidden_asset",
                        label=name,
                        aliases=aliases,
                        sourceRef=f"scenario_assets.items.{key}",
                        defaultAudience="host",
                    ))

        self.persist_index(scenario_id, items)
        logger.info("SpoilerGuard: built index for scenario %s — %d items", scenario_id, len(items))
        return items

    def persist_index(self, scenario_id: str, items: list[SpoilerSensitiveItem]) -> int:
        """UPSERT sensitive items into spoiler_sensitive_items table."""
        # Clear existing
        self.conn.execute(
            "DELETE FROM spoiler_sensitive_items WHERE scenario_id = %s",
            (scenario_id,),
        )
        for item in items:
            self.conn.execute(
                "INSERT INTO spoiler_sensitive_items "
                "(item_id, scenario_id, category, label, aliases, source_ref, default_audience) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    item.item_id, scenario_id, item.category, item.label,
                    json.dumps(item.aliases, ensure_ascii=False),
                    item.source_ref, item.default_audience,
                ),
            )
        self.conn.commit()
        return len(items)

    def load_index(self, scenario_id: str) -> list[SpoilerSensitiveItem]:
        """Load persisted sensitive items from DB for a scenario."""
        rows = self.conn.execute(
            "SELECT * FROM spoiler_sensitive_items WHERE scenario_id = %s",
            (scenario_id,),
        ).fetchall()
        items = []
        for row in rows:
            aliases_raw = row.get("aliases")
            if isinstance(aliases_raw, str):
                try:
                    aliases_raw = json.loads(aliases_raw)
                except (json.JSONDecodeError, TypeError):
                    aliases_raw = []
            items.append(SpoilerSensitiveItem(
                itemId=row["item_id"],
                scenarioId=row["scenario_id"],
                category=row["category"],
                label=row["label"],
                aliases=list(aliases_raw) if aliases_raw else [],
                sourceRef=row.get("source_ref", ""),
                defaultAudience=row.get("default_audience", "host"),
            ))
        return items

    def rebuild_index(self, scenario_id: str) -> int:
        """Full rebuild: load KG from scenarios table, extract, persist."""
        row = self.conn.execute(
            "SELECT knowledge_graph, scenario_assets FROM scenarios WHERE scenario_id = %s",
            (scenario_id,),
        ).fetchone()
        if not row:
            return 0
        kg_raw = row.get("knowledge_graph")
        if isinstance(kg_raw, str):
            try:
                kg_raw = json.loads(kg_raw)
            except (json.JSONDecodeError, TypeError):
                kg_raw = {}
        assets_raw = row.get("scenario_assets")
        if isinstance(assets_raw, str):
            try:
                assets_raw = json.loads(assets_raw)
            except (json.JSONDecodeError, TypeError):
                assets_raw = {}
        items = self.build_sensitive_index(scenario_id, kg_raw or {}, assets_raw or {})
        return len(items)

    # ── Unlock State ────────────────────────────────────────────────

    def compute_unlock_state(self, room_id: str) -> SpoilerUnlockState:
        """Aggregate all unlock sources for a room."""
        state = SpoilerUnlockState(roomId=room_id)

        # 1. Discovered clues from clues table
        clue_rows = self.conn.execute(
            "SELECT clue_id FROM clues WHERE room_id = %s",
            (room_id,),
        ).fetchall()
        state.discovered_clue_ids = [r["clue_id"] for r in clue_rows]

        # 2. Shared clues from clue_shares table
        try:
            share_rows = self.conn.execute(
                "SELECT clue_id FROM clue_shares WHERE room_id = %s",
                (room_id,),
            ).fetchall()
            state.shared_clue_ids = [r["clue_id"] for r in share_rows]
        except Exception:
            pass  # table may not exist yet

        # 3. Entered scenes / explored nodes from room_map_state
        try:
            map_rows = self.conn.execute(
                "SELECT explored_nodes FROM room_map_state WHERE room_id = %s",
                (room_id,),
            ).fetchall()
            for mr in map_rows:
                explored = mr.get("explored_nodes") or []
                if isinstance(explored, str):
                    try:
                        explored = json.loads(explored)
                    except (json.JSONDecodeError, TypeError):
                        explored = []
                state.explored_node_ids.extend(explored)
        except Exception:
            pass

        # 4. Active ending phase from events
        try:
            end_rows = self.conn.execute(
                "SELECT payload FROM events WHERE room_id = %s AND event_type = %s ORDER BY sequence DESC LIMIT 1",
                (room_id, "s2c_campaign_ended"),
            ).fetchall()
            for er in end_rows:
                payload = er.get("payload") or {}
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except (json.JSONDecodeError, TypeError):
                        payload = {}
                phase = payload.get("endingPhase", "") or payload.get("endingName", "")
                if phase:
                    state.active_ending_phase = phase
        except Exception:
            pass

        # 5. NPC appearances from events
        try:
            npc_rows = self.conn.execute(
                "SELECT payload FROM events WHERE room_id = %s AND event_type = %s ORDER BY sequence",
                (room_id, "s2c_public_observation"),
            ).fetchall()
            for nr in npc_rows:
                payload = nr.get("payload") or {}
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except (json.JSONDecodeError, TypeError):
                        payload = {}
                npc_name = payload.get("npcName", "") or payload.get("npc_name", "")
                if npc_name and npc_name not in state.revealed_npc_names:
                    state.revealed_npc_names.append(npc_name)
        except Exception:
            pass

        return state

    # ── Review ──────────────────────────────────────────────────────

    def review(
        self,
        text: str,
        audience: str,
        character_id: str | None,
        unlock_state: SpoilerUnlockState,
        sensitive_index: list[SpoilerSensitiveItem],
    ) -> SpoilerReviewResult:
        """Check text against sensitive index, accounting for unlock state and audience.

        Algorithm:
        1. Skip items already in unlock_state
        2. Skip items whose default_audience matches or is broader than target audience
        3. For remaining items, search text for exact label match and alias substring match
        4. Collect violations
        """
        if not text or not sensitive_index:
            return SpoilerReviewResult(allowed=True)

        violations: list[dict[str, Any]] = []
        text_lower = text.lower()

        for item in sensitive_index:
            # Skip if audience allows it
            if self._audience_allows(item.default_audience, audience):
                continue

            # Skip if unlocked
            if self._is_unlocked(item, unlock_state):
                continue

            # Check label
            label_lower = item.label.lower()
            if label_lower and label_lower in text_lower:
                violations.append({
                    "item_id": item.item_id,
                    "category": item.category,
                    "label": item.label,
                    "matched_text": item.label,
                    "source_ref": item.source_ref,
                })
                continue

            # Check aliases
            for alias in item.aliases:
                alias_lower = alias.lower()
                if alias_lower and len(alias_lower) >= 2 and alias_lower in text_lower:
                    violations.append({
                        "item_id": item.item_id,
                        "category": item.category,
                        "label": item.label,
                        "matched_text": alias,
                        "source_ref": item.source_ref,
                    })
                    break

        if violations:
            retry_prompt = self.generate_retry_prompt(violations)
            return SpoilerReviewResult(
                allowed=False,
                violations=violations,
                redactedReason=f"Blocked {len(violations)} sensitive item(s)",
                retryPrompt=retry_prompt,
                safeFallbackText=self.get_safe_fallback("general"),
            )

        return SpoilerReviewResult(allowed=True)

    def _audience_allows(self, default_audience: str, target_audience: str) -> bool:
        """Check if default_audience permits delivery to target_audience.

        'host' items are allowed to 'host', but NOT to 'player' or 'party'.
        'party' items are allowed to everyone.
        'player' items are allowed to 'player' and 'host'.
        """
        return self._audience_allows_static(default_audience, target_audience)

    @staticmethod
    def _audience_allows_static(default_audience: str, target_audience: str) -> bool:
        if default_audience == target_audience:
            return True
        if default_audience == "party":
            return True
        if default_audience == "host" and target_audience == "player":
            return False
        if default_audience == "host" and target_audience == "party":
            return False
        return False

    def _is_unlocked(self, item: SpoilerSensitiveItem, unlock: SpoilerUnlockState) -> bool:
        """Check if a sensitive item has been unlocked."""
        label_lower = item.label.lower()
        item_id = item.item_id
        category = item.category

        if category == "hidden_clue":
            # Check if any discovered or shared clue ID is in the source_ref
            all_clue_ids = set(unlock.discovered_clue_ids + unlock.shared_clue_ids)
            for cid in all_clue_ids:
                cid_lower = cid.lower()
                if cid_lower in item_id.lower() or cid_lower in item.source_ref.lower():
                    return True
            # Also check by label match in clue text (from source_ref)
            return False

        if category == "hidden_npc":
            for name in unlock.revealed_npc_names:
                if name.lower() == label_lower or name.lower() in label_lower or label_lower in name.lower():
                    return True
            # Also check host_manual_reveals
            for reveal in unlock.host_manual_reveals:
                if reveal.lower() == label_lower or reveal.lower() in label_lower:
                    return True
            return False

        if category == "hidden_asset":
            for reveal in unlock.host_manual_reveals:
                if reveal.lower() == label_lower or label_lower in reveal.lower():
                    return True
            return False

        if category == "ending":
            if unlock.active_ending_phase:
                return True
            return False

        # truth: never unlocked (admin-only)
        if category == "truth":
            return False

        return False

    # ── Retry & Fallback ────────────────────────────────────────────

    def generate_retry_prompt(self, violations: list[dict]) -> str:
        """Build a Chinese-language constraint prompt from violations."""
        lines = ["你的回复包含以下禁止公开的内容，请重写并避免提及："]
        for v in violations:
            cat_labels = {
                "truth": "真相",
                "ending": "结局",
                "hidden_clue": "隐藏线索",
                "hidden_npc": "隐藏NPC",
                "hidden_asset": "隐藏素材",
            }
            cat_cn = cat_labels.get(v.get("category", ""), v.get("category", ""))
            lines.append(f"  - [{cat_cn}] {v.get('label', '')}")
        lines.append("请仅使用已公开的信息重新叙述，不要暗示或透露以上任何内容。")
        return "\n".join(lines)

    def get_safe_fallback(self, category_hint: str = "general") -> str:
        """Return a template safe narrative that reveals nothing."""
        return SAFE_FALLBACK_TEMPLATES.get(category_hint, SAFE_FALLBACK_TEMPLATES["general"])

    # ── Audit Logging ───────────────────────────────────────────────

    def log_audit(
        self,
        room_id: str,
        action_id: str,
        original_text: str,
        violations: list[dict],
        retry_count: int,
        final_status: str,
        final_text: str,
        unlock_state: SpoilerUnlockState | None = None,
    ) -> str:
        """Write a spoiler audit entry and return the audit_id."""
        entry = SpoilerAuditEntry(
            roomId=room_id,
            actionId=action_id,
            originalText=original_text,
            violations=violations,
            retryCount=retry_count,
            finalStatus=final_status,
            finalText=final_text,
            unlockSnapshot=unlock_state.model_dump(by_alias=True) if unlock_state else {},
        )
        try:
            self.conn.execute(
                "INSERT INTO spoiler_audits "
                "(audit_id, room_id, action_id, original_text, violations, retry_count, final_status, final_text, unlock_snapshot) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    entry.audit_id, entry.room_id, entry.action_id, entry.original_text,
                    json.dumps(entry.violations, ensure_ascii=False),
                    entry.retry_count, entry.final_status, entry.final_text,
                    json.dumps(entry.unlock_snapshot, ensure_ascii=False),
                ),
            )
            self.conn.commit()
            logger.info("SpoilerGuard: audit logged — %s status=%s", entry.audit_id, entry.final_status)
        except Exception as e:
            logger.error("SpoilerGuard: failed to log audit: %s", e)
        return entry.audit_id

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _extract_aliases(text: str, kind: str) -> list[str]:
        """Extract alias keywords from description text.

        - Quoted names: 「...」, "...", '...'
        - Parenthetical terms: (...), （...）
        - Comma-separated terms
        """
        if not text:
            return []
        aliases: list[str] = []

        # Quoted patterns
        for pat in (r'「(.+?)」', r'"(.+?)"', r"'(.+?)'"):
            aliases.extend(re.findall(pat, text))

        # Parenthetical terms (Chinese and ASCII)
        for pat in (r'（(.+?)）', r'\((.+?)\)'):
            matches = re.findall(pat, text)
            for m in matches:
                if len(m) < 30 and len(m) > 1:
                    aliases.append(m)

        # Look for name-like patterns: 2-4 Chinese chars between whitespace/punctuation
        # Only for NPC kind
        if kind == "npc":
            name_matches = re.findall(r'(?:^|[\s，。；：])「?([一-鿿]{2,4})」?(?:[\s，。；：]|$)', text)
            for nm in name_matches:
                if nm not in aliases and len(nm) >= 2:
                    aliases.append(nm)

        # Deduplicate and clean
        seen = set()
        result = []
        for a in aliases:
            a_clean = a.strip()
            if a_clean and a_clean not in seen and len(a_clean) >= 2:
                seen.add(a_clean)
                result.append(a_clean)
        return result

    @staticmethod
    def _add_key_phrases(text: str, existing: list[str]) -> list[str]:
        """Extract key content phrases from text for broader matching.

        Splits on Chinese punctuation and extracts meaningful segments (4-20 chars).
        These serve as additional match targets beyond labels and quoted aliases.
        """
        if not text:
            return existing
        result = list(existing)
        seen = set(result)
        # Split on Chinese/ASCII punctuation
        segments = re.split(r'[，。；：！？、\n,.!?;:\s]+', text)
        for seg in segments:
            seg = seg.strip()
            # Keep segments that are meaningful sub-phrases
            if 4 <= len(seg) <= 20 and seg not in seen:
                seen.add(seg)
                result.append(seg)
        return result
