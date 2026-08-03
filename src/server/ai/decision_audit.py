import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any


_FORBIDDEN_KEYS = {
    "account_id", "actor_id", "user_id", "owner_account_id", "host_account_id",
    "actor_display_name", "declared_intent",
    "username", "email", "owner_token", "player_token", "token",
    "raw_safety_text", "safety_text", "unrelated_secret", "private_note",
    "password", "api_key", "secret",
}
_PROPOSAL_KEYS_BY_TASK = {
    "analyze_director_action": {
        "context_version", "interpreted_intent", "intent_type", "intent_contract",
        "preconditions", "permissions", "mechanic_plan", "state_patch",
        "event_plan", "reveal_proposals", "semantic_progression", "action_steps",
        "npc_reactions", "time_impact", "visibility", "basis_refs", "citations",
        "confidence", "requires_player_clarification", "clarification_options",
        "requires_host_exception", "exception_reason", "narration_mode",
        "analysis_source",
    },
    "narrate_action": {
        "context_version", "director_plan_digest", "fact_refs",
        "redacted_citations", "style_pack_version", "provider_source", "status",
    },
}
_CONTEXT_KEYS = {
    "room_id", "state_version", "context_version", "current_scene",
    "declared_intent", "intent_type", "action_id",
    "risk_contract_hash", "rule_version", "template_version", "conditions",
}
_CITATION_KEYS = {
    "citation_id", "content_item_id", "source_part_id", "source_ref", "version",
    "rule_version", "page_number", "source", "location",
    "label", "page", "scene", "verified",
}


class DecisionAuditPersistenceError(RuntimeError):
    pass


def _normalized_key(value: Any) -> str:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(value))
    return re.sub(r"[^a-z0-9]+", "_", separated.lower()).strip("_")


def _is_forbidden_key(value: Any) -> bool:
    key = _normalized_key(value)
    return (
        key in _FORBIDDEN_KEYS
        or key.endswith("_token")
        or key.endswith("_password")
        or key.endswith("_secret")
        or "api_key" in key
    )


def _clean(value: Any, *, allowed_keys: set[str] | None = None) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _clean(item)
            for key, item in value.items()
            if not _is_forbidden_key(key)
            and (allowed_keys is None or str(key) in allowed_keys)
        }
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def _clean_citation(value: dict[str, Any]) -> dict[str, Any]:
    cleaned = _clean(value, allowed_keys=_CITATION_KEYS)
    return {key: item for key, item in cleaned.items() if item is not None}


def _sensitive_context_strings(value: Any) -> set[str]:
    strings: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_forbidden_key(key):
                if isinstance(item, str) and item:
                    strings.add(item)
                elif isinstance(item, (dict, list)):
                    strings.update(_all_strings(item))
            elif isinstance(item, (dict, list)):
                strings.update(_sensitive_context_strings(item))
    elif isinstance(value, list):
        for item in value:
            strings.update(_sensitive_context_strings(item))
    return strings


def _all_strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, dict):
        result: set[str] = set()
        for item in value.values():
            result.update(_all_strings(item))
        return result
    if isinstance(value, list):
        result: set[str] = set()
        for item in value:
            result.update(_all_strings(item))
        return result
    return set()


def _redact_context_values(value: Any, sensitive_values: set[str]) -> Any:
    if isinstance(value, str):
        if any(secret in value for secret in sensitive_values):
            return "[redacted]"
        return value
    if isinstance(value, dict):
        return {
            key: _redact_context_values(item, sensitive_values)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_context_values(item, sensitive_values) for item in value]
    return value


def _clean_structured_proposal(
    task_type: str,
    proposal: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    allowed_keys = _PROPOSAL_KEYS_BY_TASK.get(task_type)
    cleaned = _clean(proposal or {}, allowed_keys=allowed_keys)
    return _redact_context_values(cleaned, _sensitive_context_strings(context or {}))


def minimal_context_hash(context: dict[str, Any] | None) -> str:
    minimal = _clean(context or {}, allowed_keys=_CONTEXT_KEYS)
    canonical = json.dumps(minimal, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DecisionAuditRecorder:
    def __init__(self, conn):
        self.conn = conn

    def record(self, *, room_id: str, action_id: str = "", task_type: str,
               provider: str, model: str, context: dict | None = None,
               template_version: str = "", rule_version: str = "",
               draft_id: str = "", draft_revision: int | None = None,
               citations: list[dict] | None = None,
               structured_proposal: dict | None = None,
               engine_validation: dict | None = None,
               final_delta: dict | None = None) -> str:
        audit_id = f"decision-{uuid.uuid4().hex}"
        expires_at = datetime.now(timezone.utc) + timedelta(days=90)
        self.conn.execute(
            "INSERT INTO ai_call_logs "
            "(decision_audit_id, room_id, action_id, task_type, provider, model, status, "
            "template_version, rule_version, context_hash, citations, structured_proposal, "
            "engine_validation, final_delta, record_kind, expires_at, draft_id, "
            "draft_revision, audit_state) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'ok', %s, %s, %s, %s, %s, %s, %s, "
            "'decision', %s, %s, %s, 'current')",
            (audit_id, room_id, action_id or None, task_type, provider, model,
             template_version, rule_version, minimal_context_hash(context),
             json.dumps([_clean_citation(c) for c in citations or []]),
             json.dumps(_clean_structured_proposal(
                 task_type,
                 structured_proposal,
                 context,
             )),
             json.dumps(_clean(engine_validation or {})),
             json.dumps(_clean(final_delta or {})), expires_at,
             draft_id or None, draft_revision),
        )
        return audit_id

    def finalize(self, action_id: str, *, engine_validation: dict | None,
                 final_delta: dict | None, task_type: str | None = None) -> int:
        assignments: list[str] = []
        params: list[Any] = []
        if engine_validation is not None:
            assignments.append("engine_validation = %s")
            params.append(json.dumps(_clean(engine_validation)))
        if final_delta is not None:
            assignments.append("final_delta = %s")
            params.append(json.dumps(_clean(final_delta)))
        if not assignments:
            return 0
        params.append(action_id)
        task_filter = ""
        if task_type:
            task_filter = " AND task_type = %s"
            params.append(task_type)
        cursor = self.conn.execute(
            f"UPDATE ai_call_logs SET {', '.join(assignments)} "
            "WHERE action_id = %s AND record_kind = 'decision'"
            f"{task_filter}",
            tuple(params),
        )
        return int(cursor.rowcount)

    def supersede_draft_revision(self, draft_id: str, draft_revision: int) -> int:
        cursor = self.conn.execute(
            "UPDATE ai_call_logs SET action_id = NULL, audit_state = 'superseded', "
            "final_delta = %s "
            "WHERE draft_id = %s AND draft_revision = %s "
            "AND record_kind = 'decision' AND audit_state = 'current'",
            (
                json.dumps({
                    "status": "superseded",
                    "reasonCode": "draft_revised",
                    "draftRevision": draft_revision,
                }),
                draft_id,
                draft_revision,
            ),
        )
        return int(cursor.rowcount)

    def finalize_draft_revision(
        self,
        draft_id: str,
        draft_revision: int,
        *,
        audit_state: str,
        final_delta: dict,
    ) -> int:
        cursor = self.conn.execute(
            "UPDATE ai_call_logs SET action_id = NULL, audit_state = %s, "
            "final_delta = %s "
            "WHERE draft_id = %s AND draft_revision = %s "
            "AND record_kind = 'decision' AND audit_state = 'current'",
            (
                audit_state,
                json.dumps(_clean(final_delta)),
                draft_id,
                draft_revision,
            ),
        )
        return int(cursor.rowcount)

    def relink_draft(
        self,
        draft_id: str,
        action_id: str,
        draft_revision: int = 1,
    ) -> int:
        cursor = self.conn.execute(
            "UPDATE ai_call_logs SET action_id = %s "
            "WHERE draft_id = %s AND draft_revision = %s "
            "AND action_id = %s AND record_kind = 'decision' "
            "AND audit_state = 'current'",
            (action_id, draft_id, draft_revision, draft_id),
        )
        return int(cursor.rowcount)

    def backfill_final_delta(self, action_id: str, final_delta: dict) -> int:
        cursor = self.conn.execute(
            "UPDATE ai_call_logs SET final_delta = %s "
            "WHERE action_id = %s AND record_kind = 'decision' "
            "AND (final_delta IS NULL OR final_delta = '{}'::jsonb)",
            (json.dumps(_clean(final_delta)), action_id),
        )
        return int(cursor.rowcount)


def finalize_terminal_decision_audit(
    conn,
    action_id: str,
    *,
    action_status: str,
    reason_code: str = "",
    effect: str = "",
    state_version: int | None = None,
) -> int:
    """Finalize every decision audit bound to an action in the caller transaction."""
    audit_rows = conn.execute(
        "SELECT decision_audit_id FROM ai_call_logs "
        "WHERE action_id = %s AND record_kind = 'decision' FOR UPDATE",
        (action_id,),
    ).fetchall()
    expected = len(audit_rows)
    if expected == 0:
        return 0

    if state_version is None:
        action_row = conn.execute(
            "SELECT rooms.state_version FROM actions "
            "JOIN rooms ON rooms.room_id = actions.room_id "
            "WHERE actions.action_id = %s",
            (action_id,),
        ).fetchone()
        if not action_row:
            raise DecisionAuditPersistenceError("decision_audit_action_missing")
        state_version = int(action_row.get("state_version") or 0)

    final_delta: dict[str, Any] = {
        "action_status": action_status,
        "state_version": int(state_version),
    }
    if reason_code:
        final_delta["reason_code"] = reason_code
    if effect:
        final_delta["effect"] = effect

    updated = DecisionAuditRecorder(conn).finalize(
        action_id,
        engine_validation=None,
        final_delta=final_delta,
    )
    if updated != expected:
        raise DecisionAuditPersistenceError("decision_audit_finalize_incomplete")
    return updated
