import json
import re
import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.pool
import psycopg2.extras

logger = logging.getLogger(__name__)

_placeholder_re = re.compile(r'\?')
_sqlite_datetime_hour_re = re.compile(r"datetime\('now',\s*'-(\d+)\s+hour'\)", re.IGNORECASE)
_sqlite_datetime_now_re = re.compile(r"datetime\('now'\)", re.IGNORECASE)


def _translate_sql(sql: str) -> str:
    sql = _sqlite_datetime_hour_re.sub(r"(NOW() - INTERVAL '\1 hour')", sql)
    sql = _sqlite_datetime_now_re.sub("NOW()", sql)
    return _placeholder_re.sub('%s', sql)


def _coerce_jsonb_result_literals(sql: str) -> str:
    lower_sql = sql.lower()
    if "insert into actions" not in lower_sql or "result" not in lower_sql:
        return sql

    match = re.search(
        r"(insert\s+into\s+actions\s*\((?P<columns>[^)]+)\)\s*values\s*\()(?P<values>.*)(\)\s*)$",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return sql

    columns = [column.strip().strip('"').lower() for column in match.group("columns").split(",")]
    if "result" not in columns:
        return sql

    values = _split_sql_values(match.group("values"))
    result_idx = columns.index("result")
    if result_idx >= len(values):
        return sql

    result_value = values[result_idx].strip()
    if len(result_value) < 2 or not (result_value.startswith("'") and result_value.endswith("'")):
        return sql

    inner = result_value[1:-1].replace("''", "'")
    try:
        json.loads(inner)
        return sql
    except Exception:
        values[result_idx] = "'" + json.dumps(inner, ensure_ascii=False).replace("'", "''") + "'"
        return match.group(1) + ", ".join(values) + match.group(4)


def _split_sql_values(values_sql: str) -> list[str]:
    values: list[str] = []
    current: list[str] = []
    in_string = False
    i = 0
    while i < len(values_sql):
        char = values_sql[i]
        if char == "'":
            current.append(char)
            if in_string and i + 1 < len(values_sql) and values_sql[i + 1] == "'":
                current.append(values_sql[i + 1])
                i += 2
                continue
            in_string = not in_string
        elif char == "," and not in_string:
            values.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        i += 1
    values.append("".join(current).strip())
    return values


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rooms (
    room_id TEXT PRIMARY KEY,
    scenario_id TEXT,
    scenario_version_id TEXT,
    runtime_package_version_id TEXT,
    owner_token TEXT NOT NULL,
    owner_account_id TEXT,
    status TEXT NOT NULL DEFAULT 'lobby',
    spoiler_level TEXT DEFAULT 'standard',
    state_version INTEGER NOT NULL DEFAULT 0,
    player_experience_version TEXT NOT NULL DEFAULT 'v2',
    action_pacing_preset TEXT NOT NULL DEFAULT 'standard',
    action_timing JSONB NOT NULL DEFAULT '{"input_hint_seconds":60,"receipt_seconds":5,"preview_seconds":30,"resolution_seconds":180}'::jsonb,
    draft_analysis_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    speech_routing TEXT NOT NULL DEFAULT 'party_message',
    host_autonomy_policy TEXT NOT NULL DEFAULT 'host_required',
    risk_contract JSONB,
    risk_contract_version TEXT,
    risk_contract_hash TEXT,
    integrity_status TEXT NOT NULL DEFAULT 'healthy',
    integrity_reason TEXT,
    integrity_source TEXT,
    integrity_state_version INTEGER,
    integrity_updated_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'player',
    last_seen_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS characters (
    character_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    player_name TEXT NOT NULL,
    player_token TEXT NOT NULL,
    xlsx_data JSONB,
    is_ready BOOLEAN NOT NULL DEFAULT FALSE,
    account_id TEXT,
    status TEXT NOT NULL DEFAULT 'joined'
);

CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id TEXT PRIMARY KEY,
    title TEXT,
    raw_text TEXT,
    knowledge_graph JSONB,
    scenario_assets JSONB,
    quality_report JSONB,
    import_status TEXT NOT NULL DEFAULT 'pending',
    publish_status TEXT NOT NULL DEFAULT 'draft',
    published_version_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS source_documents (
    source_document_id TEXT PRIMARY KEY,
    scenario_id TEXT REFERENCES scenarios(scenario_id),
    source_kind TEXT NOT NULL,
    title TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    license_type TEXT NOT NULL,
    license_ref TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (source_sha256, source_kind)
);

CREATE TABLE IF NOT EXISTS source_parts (
    source_part_id TEXT PRIMARY KEY,
    source_document_id TEXT NOT NULL REFERENCES source_documents(source_document_id),
    ordinal INTEGER NOT NULL,
    part_kind TEXT NOT NULL,
    page_number INTEGER,
    text_content TEXT NOT NULL,
    mime_type TEXT,
    storage_path TEXT,
    anchor JSONB NOT NULL DEFAULT '{}',
    checksum TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (source_document_id, ordinal)
);

CREATE TABLE IF NOT EXISTS import_jobs (
    job_id TEXT PRIMARY KEY,
    source_document_id TEXT NOT NULL REFERENCES source_documents(source_document_id),
    scenario_id TEXT REFERENCES scenarios(scenario_id),
    status TEXT NOT NULL DEFAULT 'pending',
    progress INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    diagnostics JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scenario_versions (
    scenario_version_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
    version_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    knowledge_graph JSONB NOT NULL DEFAULT '{}',
    quality_report JSONB NOT NULL DEFAULT '{}',
    prep_package JSONB NOT NULL DEFAULT '{}',
    rag_index_version TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    reviewed_by TEXT,
    reviewed_at TIMESTAMP,
    review_notes JSONB NOT NULL DEFAULT '{}',
    published_at TIMESTAMP,
    UNIQUE (scenario_id, version_number)
);

CREATE TABLE IF NOT EXISTS scenario_version_sources (
    scenario_version_id TEXT NOT NULL REFERENCES scenario_versions(scenario_version_id),
    source_document_id TEXT NOT NULL REFERENCES source_documents(source_document_id),
    ordinal INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (scenario_version_id, source_document_id),
    UNIQUE (scenario_version_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_scenario_version_sources_document
    ON scenario_version_sources(source_document_id);

CREATE TABLE IF NOT EXISTS scenario_review_drafts (
    scenario_version_id TEXT PRIMARY KEY REFERENCES scenario_versions(scenario_version_id) ON DELETE CASCADE,
    parent_version_id TEXT NOT NULL REFERENCES scenario_versions(scenario_version_id),
    created_by TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scenario_review_drafts_parent
    ON scenario_review_drafts(parent_version_id, created_at DESC);

CREATE TABLE IF NOT EXISTS scenario_review_patches (
    review_patch_id TEXT PRIMARY KEY,
    scenario_version_id TEXT NOT NULL REFERENCES scenario_versions(scenario_version_id) ON DELETE CASCADE,
    target_type TEXT NOT NULL,
    target_key TEXT NOT NULL,
    operation TEXT NOT NULL DEFAULT 'upsert',
    payload JSONB NOT NULL DEFAULT '{}',
    provenance TEXT NOT NULL,
    citation JSONB NOT NULL DEFAULT '{}',
    rationale TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'accepted',
    created_by TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scenario_review_patches_version
    ON scenario_review_patches(scenario_version_id, status, created_at);

CREATE TABLE IF NOT EXISTS scenario_review_issue_resolutions (
    scenario_version_id TEXT NOT NULL REFERENCES scenario_versions(scenario_version_id) ON DELETE CASCADE,
    issue_code TEXT NOT NULL,
    status TEXT NOT NULL,
    rationale TEXT NOT NULL,
    resolved_by TEXT NOT NULL,
    resolved_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (scenario_version_id, issue_code)
);

CREATE TABLE IF NOT EXISTS content_items (
    content_item_id TEXT PRIMARY KEY,
    scenario_version_id TEXT NOT NULL REFERENCES scenario_versions(scenario_version_id) ON DELETE CASCADE,
    source_part_id TEXT REFERENCES source_parts(source_part_id),
    item_type TEXT NOT NULL,
    logical_key TEXT NOT NULL,
    title TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'host_only',
    payload JSONB NOT NULL DEFAULT '{}',
    citation JSONB NOT NULL DEFAULT '{}',
    checksum TEXT NOT NULL,
    ordinal INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (scenario_version_id, item_type, logical_key)
);

CREATE INDEX IF NOT EXISTS idx_content_items_version_visibility
    ON content_items(scenario_version_id, visibility, item_type, ordinal);
CREATE INDEX IF NOT EXISTS idx_content_items_source_part
    ON content_items(source_part_id);

CREATE TABLE IF NOT EXISTS content_item_edges (
    content_item_edge_id TEXT PRIMARY KEY,
    scenario_version_id TEXT NOT NULL REFERENCES scenario_versions(scenario_version_id) ON DELETE CASCADE,
    from_content_item_id TEXT NOT NULL REFERENCES content_items(content_item_id) ON DELETE CASCADE,
    to_content_item_id TEXT NOT NULL REFERENCES content_items(content_item_id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    conditions JSONB NOT NULL DEFAULT '[]',
    citation JSONB NOT NULL DEFAULT '{}',
    ordinal INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (scenario_version_id, from_content_item_id, to_content_item_id, relation_type, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_content_item_edges_from
    ON content_item_edges(scenario_version_id, from_content_item_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_content_item_edges_to
    ON content_item_edges(scenario_version_id, to_content_item_id, relation_type);

CREATE TABLE IF NOT EXISTS content_projection_runs (
    projection_run_id TEXT PRIMARY KEY,
    scenario_version_id TEXT NOT NULL REFERENCES scenario_versions(scenario_version_id) ON DELETE CASCADE,
    projection_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    input_checksum TEXT NOT NULL,
    output_checksum TEXT,
    diagnostics JSONB NOT NULL DEFAULT '{}',
    requested_by TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_content_projection_runs_version_started
    ON content_projection_runs(scenario_version_id, started_at DESC);

CREATE TABLE IF NOT EXISTS runtime_package_versions (
    runtime_package_version_id TEXT PRIMARY KEY,
    scenario_version_id TEXT NOT NULL REFERENCES scenario_versions(scenario_version_id) ON DELETE CASCADE,
    package_version_number INTEGER NOT NULL,
    gate_status TEXT NOT NULL,
    input_checksum TEXT NOT NULL,
    runtime_package JSONB NOT NULL DEFAULT '{}',
    quality_exceptions JSONB NOT NULL DEFAULT '[]',
    created_by TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (scenario_version_id, package_version_number),
    CHECK (gate_status IN ('ready', 'blocked'))
);

CREATE INDEX IF NOT EXISTS idx_runtime_package_versions_latest
    ON runtime_package_versions(scenario_version_id, package_version_number DESC);

CREATE TABLE IF NOT EXISTS runtime_package_exception_confirmations (
    runtime_package_version_id TEXT NOT NULL REFERENCES runtime_package_versions(runtime_package_version_id) ON DELETE CASCADE,
    exception_key TEXT NOT NULL,
    confirmed_by TEXT NOT NULL,
    confirmed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (runtime_package_version_id, exception_key)
);

CREATE TABLE IF NOT EXISTS v2_cutover_records (
    cutover_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    room_count INTEGER NOT NULL DEFAULT 0,
    backup_path TEXT NOT NULL,
    backup_sha256 TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rag_rebuild_records (
    rebuild_id TEXT PRIMARY KEY,
    scenario_version_id TEXT NOT NULL REFERENCES scenario_versions(scenario_version_id),
    status TEXT NOT NULL DEFAULT 'running',
    embedding_model TEXT,
    embedding_dimensions INTEGER,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    requested_by TEXT NOT NULL,
    error_message TEXT,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_rebuild_records_version_started
    ON rag_rebuild_records(scenario_version_id, started_at);

CREATE TABLE IF NOT EXISTS rule_sets (
    rule_set_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    system TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_base BOOLEAN NOT NULL DEFAULT FALSE,
    license_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rule_sets_system_base_status
    ON rule_sets(system, is_base, status);

CREATE TABLE IF NOT EXISTS rule_set_versions (
    rule_set_version_id TEXT PRIMARY KEY,
    rule_set_id TEXT NOT NULL REFERENCES rule_sets(rule_set_id),
    version_number INTEGER NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    source_sha256 TEXT,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    published_at TIMESTAMP,
    UNIQUE (rule_set_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_rule_set_versions_set_status
    ON rule_set_versions(rule_set_id, status);

CREATE TABLE IF NOT EXISTS scenario_rule_bindings (
    scenario_version_id TEXT NOT NULL REFERENCES scenario_versions(scenario_version_id),
    rule_set_version_id TEXT NOT NULL REFERENCES rule_set_versions(rule_set_version_id),
    priority INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (scenario_version_id, rule_set_version_id)
);

CREATE INDEX IF NOT EXISTS idx_scenario_rule_bindings_priority
    ON scenario_rule_bindings(scenario_version_id, priority);

CREATE TABLE IF NOT EXISTS room_rule_bindings (
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    rule_set_version_id TEXT NOT NULL REFERENCES rule_set_versions(rule_set_version_id),
    priority INTEGER NOT NULL DEFAULT 200,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (room_id, rule_set_version_id)
);

CREATE INDEX IF NOT EXISTS idx_room_rule_bindings_priority
    ON room_rule_bindings(room_id, priority);

CREATE TABLE IF NOT EXISTS character_templates (
    template_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
    name TEXT NOT NULL,
    occupation TEXT,
    background TEXT,
    age INTEGER DEFAULT 25,
    gender TEXT DEFAULT '',
    attributes JSONB DEFAULT '{}',
    skills JSONB DEFAULT '{}',
    backstory JSONB DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
    sequence BIGSERIAL PRIMARY KEY,
    room_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    audience TEXT NOT NULL,
    payload JSONB NOT NULL,
    action_id TEXT,
    state_version INTEGER,
    payload_hash TEXT NOT NULL DEFAULT '',
    issued_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS actions (
    action_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    draft_id TEXT,
    idempotency_key TEXT,
    revision_number INTEGER NOT NULL DEFAULT 1,
    intent_type TEXT NOT NULL,
    declared_intent TEXT,
    params JSONB DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    batch_id TEXT,
    rule_set_version_id TEXT,
    receipt JSONB,
    result JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    canceled_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prepared_rule_actions (
    action_id TEXT PRIMARY KEY REFERENCES actions(action_id) ON DELETE CASCADE,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    trigger_kind TEXT NOT NULL,
    reaction_kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'armed'
        CHECK (status IN ('armed', 'triggered', 'completed', 'rejected', 'timeout', 'canceled', 'expired')),
    source_action_id TEXT REFERENCES actions(action_id) ON DELETE SET NULL,
    expires_at TIMESTAMP NOT NULL DEFAULT (NOW() + INTERVAL '15 minutes'),
    triggered_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prepared_rule_actions_one_armed_per_character
    ON prepared_rule_actions(room_id, character_id)
    WHERE status = 'armed';
CREATE INDEX IF NOT EXISTS idx_prepared_rule_actions_trigger
    ON prepared_rule_actions(room_id, trigger_kind, status, expires_at);
ALTER TABLE prepared_rule_actions
    DROP CONSTRAINT IF EXISTS prepared_rule_actions_status_check;
ALTER TABLE prepared_rule_actions
    ADD CONSTRAINT prepared_rule_actions_status_check
    CHECK (status IN ('armed', 'triggered', 'completed', 'rejected', 'timeout', 'canceled', 'expired'));

CREATE TABLE IF NOT EXISTS resolution_bundles (
    action_id TEXT PRIMARY KEY REFERENCES actions(action_id) ON DELETE CASCADE,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    canonical_result JSONB NOT NULL,
    rule_explanation JSONB NOT NULL,
    actor_projection JSONB NOT NULL,
    stage_projection JSONB NOT NULL,
    host_console JSONB NOT NULL,
    release_status TEXT NOT NULL DEFAULT 'ready'
        CHECK (release_status IN ('ready', 'released', 'projection_pending')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    released_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_resolution_bundles_room_created
    ON resolution_bundles(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_resolution_bundles_room_release
    ON resolution_bundles(room_id, release_status, created_at);

CREATE TABLE IF NOT EXISTS action_drafts (
    draft_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    turn_id TEXT,
    base_state_version INTEGER NOT NULL DEFAULT 0,
    intent_type TEXT NOT NULL,
    declared_intent TEXT NOT NULL DEFAULT '',
    params JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'analyzing',
    risk_level TEXT NOT NULL DEFAULT 'low',
    analysis JSONB NOT NULL DEFAULT '{}',
    current_revision INTEGER NOT NULL DEFAULT 1,
    expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS player_action_submissions (
    action_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    input_mode TEXT NOT NULL,
    raw_text_ciphertext TEXT NOT NULL,
    requested_visibility TEXT NOT NULL DEFAULT 'public',
    client_sequence INTEGER,
    base_state_version INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'received',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_player_action_submissions_character_created
    ON player_action_submissions(character_id, created_at DESC);

CREATE TABLE IF NOT EXISTS action_draft_revisions (
    revision_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL REFERENCES action_drafts(draft_id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL,
    declared_intent TEXT NOT NULL DEFAULT '',
    analysis JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (draft_id, revision_number)
);

CREATE TABLE IF NOT EXISTS action_status_events (
    status_event_id BIGSERIAL PRIMARY KEY,
    action_id TEXT NOT NULL REFERENCES actions(action_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS action_consents (
    consent_id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL REFERENCES actions(action_id) ON DELETE CASCADE,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    requester_character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    affected_character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    consent_kind TEXT NOT NULL,
    decision TEXT NOT NULL DEFAULT 'pending'
        CHECK (decision IN ('pending', 'accepted', 'rejected', 'expired')),
    expires_at TIMESTAMP NOT NULL,
    responded_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (action_id, affected_character_id, consent_kind)
);

CREATE INDEX IF NOT EXISTS idx_action_consents_affected_pending
    ON action_consents(affected_character_id, decision, expires_at);
CREATE INDEX IF NOT EXISTS idx_action_consents_action
    ON action_consents(action_id, consent_kind);

CREATE TABLE IF NOT EXISTS action_review_requests (
    review_request_id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL REFERENCES actions(action_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    original_intent TEXT NOT NULL DEFAULT '',
    objection TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    ai_suggestion JSONB NOT NULL DEFAULT '{}',
    host_resolution JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS compensation_transactions (
    transaction_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    review_request_id TEXT REFERENCES action_review_requests(review_request_id) ON DELETE SET NULL,
    transaction_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    applied_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS room_player_settings (
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    draft_analysis_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    absent_policy TEXT NOT NULL DEFAULT 'idle',
    controller_device_id TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (room_id, character_id)
);

CREATE TABLE IF NOT EXISTS collaboration_contracts (
    contract_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    initiator_character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    shared_intent TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'canceled', 'expired')),
    expires_at TIMESTAMP NOT NULL,
    accepted_at TIMESTAMP,
    canceled_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS collaboration_contract_participants (
    contract_id TEXT NOT NULL REFERENCES collaboration_contracts(contract_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('initiator', 'invitee')),
    invite_order INTEGER NOT NULL DEFAULT 0,
    decision TEXT NOT NULL DEFAULT 'pending'
        CHECK (decision IN ('pending', 'accepted', 'declined')),
    responded_at TIMESTAMP,
    PRIMARY KEY (contract_id, character_id)
);

CREATE TABLE IF NOT EXISTS collaboration_contract_drafts (
    contract_id TEXT NOT NULL REFERENCES collaboration_contracts(contract_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    draft_id TEXT NOT NULL UNIQUE REFERENCES action_drafts(draft_id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (contract_id, character_id)
);

CREATE TABLE IF NOT EXISTS collaboration_contract_batches (
    contract_id TEXT PRIMARY KEY REFERENCES collaboration_contracts(contract_id) ON DELETE CASCADE,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    action_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'resolving', 'completed', 'blocked', 'canceled')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_collaboration_contracts_room_status
    ON collaboration_contracts(room_id, status, expires_at);
CREATE INDEX IF NOT EXISTS idx_collaboration_contract_participants_character
    ON collaboration_contract_participants(character_id, decision);
ALTER TABLE collaboration_contracts
    DROP CONSTRAINT IF EXISTS collaboration_contracts_status_check;
ALTER TABLE collaboration_contracts
    ADD CONSTRAINT collaboration_contracts_status_check
    CHECK (status IN ('pending', 'accepted', 'completed', 'canceled', 'expired'));
ALTER TABLE collaboration_contract_participants
    ADD COLUMN IF NOT EXISTS invite_order INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS player_device_sessions (
    device_session_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    device_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    is_controller BOOLEAN NOT NULL DEFAULT FALSE,
    last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (character_id, device_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_player_device_active_controller
    ON player_device_sessions(character_id)
    WHERE status = 'active' AND is_controller;
CREATE INDEX IF NOT EXISTS idx_player_device_sessions_room_last_seen
    ON player_device_sessions(room_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS campaign_sessions (
    campaign_session_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',
    started_by_character_id TEXT REFERENCES characters(character_id) ON DELETE SET NULL,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMP NOT NULL DEFAULT NOW(),
    scheduled_for TIMESTAMP,
    ended_at TIMESTAMP,
    end_reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_campaign_sessions_active_room
    ON campaign_sessions(room_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_campaign_sessions_room_status
    ON campaign_sessions(room_id, status, started_at DESC);

CREATE TABLE IF NOT EXISTS session_summaries (
    session_summary_id TEXT PRIMARY KEY,
    campaign_session_id TEXT NOT NULL REFERENCES campaign_sessions(campaign_session_id) ON DELETE CASCADE,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    summary_text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'local_fallback',
    confidence NUMERIC(4,3) NOT NULL DEFAULT 1.0,
    published_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS session_summary_citations (
    session_summary_citation_id TEXT PRIMARY KEY,
    session_summary_id TEXT NOT NULL REFERENCES session_summaries(session_summary_id) ON DELETE CASCADE,
    event_sequence BIGINT REFERENCES events(sequence) ON DELETE SET NULL,
    citation_label TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS session_attendance (
    campaign_session_id TEXT NOT NULL REFERENCES campaign_sessions(campaign_session_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    attendance_status TEXT NOT NULL DEFAULT 'present',
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (campaign_session_id, character_id)
);

CREATE TABLE IF NOT EXISTS session_zero_confirmations (
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    step TEXT NOT NULL,
    contract_version TEXT,
    contract_hash TEXT,
    confirmed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (room_id, character_id, step)
);

CREATE TABLE IF NOT EXISTS player_notes (
    note_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    parent_note_id TEXT REFERENCES player_notes(note_id) ON DELETE SET NULL,
    title_ciphertext TEXT NOT NULL,
    body_ciphertext TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'private',
    is_redacted_copy BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_player_notes_room_visibility
    ON player_notes(room_id, visibility, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_player_notes_character
    ON player_notes(character_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS note_attachments (
    note_attachment_id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL REFERENCES player_notes(note_id) ON DELETE CASCADE,
    filename_ciphertext TEXT NOT NULL,
    content_type TEXT NOT NULL,
    content_ciphertext TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (note_id)
);

CREATE TABLE IF NOT EXISTS private_data_access_audits (
    private_data_access_audit_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    note_id TEXT NOT NULL REFERENCES player_notes(note_id) ON DELETE CASCADE,
    owner_character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    host_account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE RESTRICT,
    reason TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evidence_cards (
    evidence_card_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    created_by_character_id TEXT REFERENCES characters(character_id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    card_type TEXT NOT NULL DEFAULT 'clue',
    fact_status TEXT NOT NULL DEFAULT 'hypothesis',
    visibility TEXT NOT NULL DEFAULT 'private',
    source TEXT NOT NULL DEFAULT 'player',
    confirmed_by TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evidence_cards_room_visibility
    ON evidence_cards(room_id, visibility, updated_at DESC);

ALTER TABLE evidence_cards ALTER COLUMN visibility SET DEFAULT 'private';

ALTER TABLE evidence_cards ADD COLUMN IF NOT EXISTS question_status TEXT;
ALTER TABLE evidence_cards ADD COLUMN IF NOT EXISTS question_closed_by_character_id TEXT;
ALTER TABLE evidence_cards ADD COLUMN IF NOT EXISTS question_closed_at TIMESTAMP;
ALTER TABLE evidence_cards ADD COLUMN IF NOT EXISTS question_undo_until TIMESTAMP;
UPDATE evidence_cards
SET question_status = 'investigating'
WHERE card_type = 'question' AND question_status IS NULL;
CREATE INDEX IF NOT EXISTS idx_evidence_cards_open_questions
    ON evidence_cards(room_id, question_status, updated_at DESC)
    WHERE card_type = 'question' AND visibility = 'party';

ALTER TABLE evidence_cards ADD COLUMN IF NOT EXISTS hypothesis_status TEXT;
ALTER TABLE evidence_cards ADD COLUMN IF NOT EXISTS hypothesis_previous_status TEXT;
ALTER TABLE evidence_cards ADD COLUMN IF NOT EXISTS hypothesis_status_changed_by_character_id TEXT;
ALTER TABLE evidence_cards ADD COLUMN IF NOT EXISTS hypothesis_status_changed_at TIMESTAMP;
ALTER TABLE evidence_cards ADD COLUMN IF NOT EXISTS hypothesis_status_undo_until TIMESTAMP;
UPDATE evidence_cards
SET hypothesis_status = 'discussing'
WHERE card_type <> 'question'
  AND visibility = 'party'
  AND source = 'player'
  AND fact_status = 'hypothesis'
  AND hypothesis_status IS NULL;
CREATE INDEX IF NOT EXISTS idx_evidence_cards_shared_hypothesis_status
    ON evidence_cards(room_id, hypothesis_status, updated_at DESC)
    WHERE card_type <> 'question' AND visibility = 'party' AND source = 'player';

CREATE TABLE IF NOT EXISTS evidence_links (
    evidence_link_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    from_evidence_card_id TEXT NOT NULL REFERENCES evidence_cards(evidence_card_id) ON DELETE CASCADE,
    to_evidence_card_id TEXT NOT NULL REFERENCES evidence_cards(evidence_card_id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'related',
    created_by_character_id TEXT REFERENCES characters(character_id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (from_evidence_card_id, to_evidence_card_id, relation_type)
);

CREATE TABLE IF NOT EXISTS evidence_comments (
    evidence_comment_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    evidence_card_id TEXT NOT NULL REFERENCES evidence_cards(evidence_card_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evidence_comments_card_created
    ON evidence_comments(evidence_card_id, created_at ASC);

CREATE TABLE IF NOT EXISTS evidence_references (
    evidence_reference_id TEXT PRIMARY KEY,
    evidence_card_id TEXT NOT NULL REFERENCES evidence_cards(evidence_card_id) ON DELETE CASCADE,
    reference_type TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    citation JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_action_drafts_character_status
    ON action_drafts(character_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_action_status_events_action
    ON action_status_events(action_id, status_event_id);
CREATE INDEX IF NOT EXISTS idx_action_reviews_status
    ON action_review_requests(status, created_at);

CREATE TABLE IF NOT EXISTS player_sequences (
    character_id TEXT NOT NULL,
    room_id TEXT NOT NULL,
    last_delivered_sequence BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (character_id, room_id)
);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    state_snapshot JSONB NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    state_version INTEGER NOT NULL DEFAULT 0,
    event_sequence BIGINT NOT NULL DEFAULT 0,
    snapshot_sha256 TEXT NOT NULL DEFAULT '',
    invariant_report JSONB NOT NULL DEFAULT '{}',
    verification_status TEXT NOT NULL DEFAULT 'unverified',
    checkpoint_type TEXT NOT NULL DEFAULT 'manual',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaign_archives (
    archive_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    ending_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    highlights JSONB NOT NULL,
    character_arcs JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clues (
    clue_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT DEFAULT '',
    is_private BOOLEAN NOT NULL DEFAULT TRUE,
    discovered_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clue_shares (
    share_id TEXT PRIMARY KEY,
    clue_id TEXT NOT NULL REFERENCES clues(clue_id),
    shared_by TEXT NOT NULL,
    shared_at TIMESTAMP NOT NULL DEFAULT NOW(),
    public_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS objectives (
    objective_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    character_id TEXT,
    text TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'team',
    status TEXT NOT NULL DEFAULT 'active',
    assigned_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inventory (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    room_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    quantity INTEGER DEFAULT 1,
    is_secret BOOLEAN DEFAULT FALSE,
    source TEXT DEFAULT '',
    acquired_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inventory_transfer_requests (
    transfer_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    from_character_id TEXT NOT NULL,
    to_character_id TEXT NOT NULL,
    item_name TEXT NOT NULL,
    item_is_secret BOOLEAN NOT NULL DEFAULT FALSE,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    status TEXT NOT NULL DEFAULT 'pending',
    result_item_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_inventory_transfer_requests_recipient
    ON inventory_transfer_requests(to_character_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inventory_transfer_requests_item
    ON inventory_transfer_requests(item_id, status);

CREATE TABLE IF NOT EXISTS clarifications (
    clarification_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    target_action_id TEXT NOT NULL,
    text TEXT NOT NULL,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    window_expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP,
    result JSONB
);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    room_id TEXT,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    source_part_id TEXT,
    scenario_version_id TEXT,
    rule_set_version_id TEXT,
    visibility TEXT NOT NULL DEFAULT 'internal',
    citation JSONB DEFAULT '{}',
    embedding_model TEXT,
    embedding_dimensions INTEGER,
    embedding vector,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_source ON document_chunks(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_chunks_room ON document_chunks(room_id);
CREATE INDEX IF NOT EXISTS idx_scenario_versions_scenario_status ON scenario_versions(scenario_id, status);

CREATE TABLE IF NOT EXISTS host_states (
    room_id TEXT PRIMARY KEY REFERENCES rooms(room_id),
    state JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS room_turns (
    turn_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    turn_index INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'collecting',
    mode TEXT NOT NULL DEFAULT 'scene',
    encounter_id TEXT,
    combat_plan JSONB NOT NULL DEFAULT '{}',
    combat_summary JSONB NOT NULL DEFAULT '{}',
    base_state_version INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP,
    summary TEXT
);

ALTER TABLE actions ADD COLUMN IF NOT EXISTS turn_id TEXT;
ALTER TABLE room_turns ADD COLUMN IF NOT EXISTS base_state_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE room_turns ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'scene';
ALTER TABLE room_turns ADD COLUMN IF NOT EXISTS encounter_id TEXT;
ALTER TABLE room_turns ADD COLUMN IF NOT EXISTS combat_plan JSONB NOT NULL DEFAULT '{}';
ALTER TABLE room_turns ADD COLUMN IF NOT EXISTS combat_summary JSONB NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS rule_documents (
    doc_id TEXT PRIMARY KEY,
    rule_set_version_id TEXT REFERENCES rule_set_versions(rule_set_version_id),
    source_document_id TEXT REFERENCES source_documents(source_document_id),
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'host_only',
    license_type TEXT NOT NULL DEFAULT 'authorized',
    source_ref TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE rule_documents ADD COLUMN IF NOT EXISTS rule_set_version_id TEXT REFERENCES rule_set_versions(rule_set_version_id);
ALTER TABLE rule_documents ADD COLUMN IF NOT EXISTS source_document_id TEXT REFERENCES source_documents(source_document_id);
ALTER TABLE rule_documents ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'host_only';
ALTER TABLE rule_documents ADD COLUMN IF NOT EXISTS license_type TEXT NOT NULL DEFAULT 'authorized';
ALTER TABLE rule_documents ADD COLUMN IF NOT EXISTS source_ref TEXT;

CREATE INDEX IF NOT EXISTS idx_rule_documents_version_category
    ON rule_documents(rule_set_version_id, category);

CREATE TABLE IF NOT EXISTS scenario_assets (
    asset_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    file_size INTEGER NOT NULL DEFAULT 0,
    relative_path TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS scenario_assets JSONB;
ALTER TABLE scenario_assets ADD COLUMN IF NOT EXISTS visibility TEXT DEFAULT 'host_only';
ALTER TABLE scenario_assets ADD COLUMN IF NOT EXISTS source_document_id TEXT REFERENCES source_documents(source_document_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_scenario_assets_source_document
    ON scenario_assets(source_document_id) WHERE source_document_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS scenario_asset_bindings (
    binding_id TEXT PRIMARY KEY,
    scenario_version_id TEXT NOT NULL REFERENCES scenario_versions(scenario_version_id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES scenario_assets(asset_id) ON DELETE CASCADE,
    target_type TEXT NOT NULL,
    target_key TEXT NOT NULL DEFAULT '',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    evidence JSONB NOT NULL DEFAULT '{}',
    generated_by TEXT NOT NULL DEFAULT 'local',
    status TEXT NOT NULL DEFAULT 'draft',
    reviewed_by TEXT,
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (scenario_version_id, asset_id),
    CHECK (target_type IN ('map', 'branch_node', 'scene', 'item', 'clue', 'npc', 'ending')),
    CHECK (status IN ('draft', 'confirmed', 'rejected', 'stale'))
);
CREATE INDEX IF NOT EXISTS idx_scenario_asset_bindings_target
    ON scenario_asset_bindings(scenario_version_id, target_type, target_key, status);
ALTER TABLE scenario_asset_bindings ADD COLUMN IF NOT EXISTS evidence JSONB NOT NULL DEFAULT '{}';
ALTER TABLE scenario_asset_bindings ADD COLUMN IF NOT EXISTS generated_by TEXT NOT NULL DEFAULT 'local';
ALTER TABLE scenario_asset_bindings ADD COLUMN IF NOT EXISTS reviewed_by TEXT;
ALTER TABLE scenario_asset_bindings ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP;
ALTER TABLE scenario_asset_bindings ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();
ALTER TABLE actions ADD COLUMN IF NOT EXISTS params JSONB DEFAULT '{}';
ALTER TABLE actions ADD COLUMN IF NOT EXISTS draft_id TEXT;
ALTER TABLE actions ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE actions ADD COLUMN IF NOT EXISTS revision_number INTEGER NOT NULL DEFAULT 1;
ALTER TABLE actions ADD COLUMN IF NOT EXISTS rule_set_version_id TEXT;
ALTER TABLE actions ADD COLUMN IF NOT EXISTS receipt JSONB;
ALTER TABLE actions ADD COLUMN IF NOT EXISTS canceled_at TIMESTAMP;
ALTER TABLE action_drafts ADD COLUMN IF NOT EXISTS base_state_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE action_drafts ADD COLUMN IF NOT EXISTS params JSONB NOT NULL DEFAULT '{}';
CREATE UNIQUE INDEX IF NOT EXISTS uq_actions_character_idempotency
    ON actions(character_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_actions_effective_per_turn
    ON actions(turn_id, character_id)
    WHERE turn_id IS NOT NULL AND status NOT IN ('rejected', 'canceled', 'timeout');
CREATE TABLE IF NOT EXISTS resolution_bundles (
    action_id TEXT PRIMARY KEY REFERENCES actions(action_id) ON DELETE CASCADE,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    canonical_result JSONB NOT NULL,
    rule_explanation JSONB NOT NULL,
    actor_projection JSONB NOT NULL,
    stage_projection JSONB NOT NULL,
    host_console JSONB NOT NULL,
    release_status TEXT NOT NULL DEFAULT 'ready'
        CHECK (release_status IN ('ready', 'released', 'projection_pending')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    released_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_resolution_bundles_room_created
    ON resolution_bundles(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_resolution_bundles_room_release
    ON resolution_bundles(room_id, release_status, created_at);
ALTER TABLE resolution_bundles
    DROP CONSTRAINT IF EXISTS resolution_bundles_release_status_check;
ALTER TABLE resolution_bundles
    ADD CONSTRAINT resolution_bundles_release_status_check
    CHECK (release_status IN ('ready', 'released', 'projection_pending'));
ALTER TABLE characters ADD COLUMN IF NOT EXISTS account_id TEXT;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'player';
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS owner_account_id TEXT;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS player_experience_version TEXT NOT NULL DEFAULT 'v1';
ALTER TABLE rooms ALTER COLUMN player_experience_version SET DEFAULT 'v2';
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS action_pacing_preset TEXT NOT NULL DEFAULT 'standard';
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS action_timing JSONB NOT NULL DEFAULT '{"input_hint_seconds":60,"receipt_seconds":5,"preview_seconds":30,"resolution_seconds":180}'::jsonb;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS draft_analysis_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS speech_routing TEXT NOT NULL DEFAULT 'party_message';
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS host_autonomy_policy TEXT NOT NULL DEFAULT 'host_required';
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS risk_contract JSONB;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS risk_contract_version TEXT;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS risk_contract_hash TEXT;
ALTER TABLE session_zero_confirmations ADD COLUMN IF NOT EXISTS contract_version TEXT;
ALTER TABLE session_zero_confirmations ADD COLUMN IF NOT EXISTS contract_hash TEXT;
ALTER TABLE room_player_settings ADD COLUMN IF NOT EXISTS absent_policy TEXT NOT NULL DEFAULT 'idle';
ALTER TABLE characters ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'joined';
-- Fix default for databases created before migration
ALTER TABLE characters ALTER COLUMN status SET DEFAULT 'joined';
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS source_filename TEXT;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS source_sha256 TEXT;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS original_file_path TEXT;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS publish_status TEXT NOT NULL DEFAULT 'draft';
UPDATE scenarios SET publish_status = 'draft' WHERE publish_status IS NULL;
ALTER TABLE scenarios ALTER COLUMN publish_status SET DEFAULT 'draft';
ALTER TABLE scenarios ALTER COLUMN publish_status SET NOT NULL;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS published_version_id TEXT;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS scenario_version_id TEXT;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS runtime_package_version_id TEXT;
UPDATE rooms
SET runtime_package_version_id = (
    SELECT runtime_package_version_id
    FROM runtime_package_versions
    WHERE scenario_version_id = rooms.scenario_version_id
      AND gate_status = 'ready'
    ORDER BY package_version_number DESC
    LIMIT 1
)
WHERE runtime_package_version_id IS NULL
  AND scenario_version_id IS NOT NULL
  AND EXISTS (
      SELECT 1
      FROM runtime_package_versions
      WHERE scenario_version_id = rooms.scenario_version_id
        AND gate_status = 'ready'
  );
ALTER TABLE scenario_versions ADD COLUMN IF NOT EXISTS reviewed_by TEXT;
ALTER TABLE scenario_versions ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP;
ALTER TABLE scenario_versions ADD COLUMN IF NOT EXISTS review_notes JSONB NOT NULL DEFAULT '{}';
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS source_part_id TEXT;
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS scenario_version_id TEXT;
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS rule_set_version_id TEXT;
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'internal';
UPDATE document_chunks SET visibility = 'internal' WHERE visibility IS NULL;
ALTER TABLE document_chunks ALTER COLUMN visibility SET DEFAULT 'internal';
ALTER TABLE document_chunks ALTER COLUMN visibility SET NOT NULL;
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS citation JSONB DEFAULT '{}';
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding_model TEXT;
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding_dimensions INTEGER;
ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector USING embedding::vector;
CREATE INDEX IF NOT EXISTS idx_chunks_version_visibility ON document_chunks(scenario_version_id, visibility);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_space
    ON document_chunks(embedding_model, embedding_dimensions);
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name
         AND tc.table_schema = ccu.table_schema
        WHERE tc.table_schema = 'public'
          AND tc.table_name = 'source_documents'
          AND tc.constraint_type = 'FOREIGN KEY'
          AND kcu.column_name = 'scenario_id'
          AND ccu.table_name = 'scenarios'
          AND ccu.column_name = 'scenario_id'
    ) THEN
        ALTER TABLE source_documents
            ADD CONSTRAINT fk_source_documents_scenario_id
            FOREIGN KEY (scenario_id) REFERENCES scenarios(scenario_id);
    END IF;
END $$;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name
         AND tc.table_schema = ccu.table_schema
        WHERE tc.table_schema = 'public'
          AND tc.table_name = 'import_jobs'
          AND tc.constraint_type = 'FOREIGN KEY'
          AND kcu.column_name = 'scenario_id'
          AND ccu.table_name = 'scenarios'
          AND ccu.column_name = 'scenario_id'
    ) THEN
        ALTER TABLE import_jobs
            ADD CONSTRAINT fk_import_jobs_scenario_id
            FOREIGN KEY (scenario_id) REFERENCES scenarios(scenario_id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS scenario_maps (
    map_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
    generated_by TEXT NOT NULL DEFAULT 'python',
    status TEXT NOT NULL DEFAULT 'draft',
    nodes JSONB NOT NULL DEFAULT '[]',
    edges JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    confirmed_at TIMESTAMP
);

ALTER TABLE scenario_maps ADD COLUMN IF NOT EXISTS map_type TEXT NOT NULL DEFAULT 'graph';
ALTER TABLE scenario_maps ADD COLUMN IF NOT EXISTS base_asset JSONB NOT NULL DEFAULT '{}';
ALTER TABLE scenario_maps ADD COLUMN IF NOT EXISTS regions JSONB NOT NULL DEFAULT '[]';
ALTER TABLE scenario_maps ADD COLUMN IF NOT EXISTS paths JSONB NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS room_map_state (
    room_id TEXT PRIMARY KEY REFERENCES rooms(room_id),
    map_id TEXT NOT NULL,
    explored_nodes JSONB NOT NULL DEFAULT '[]',
    hidden_nodes JSONB NOT NULL DEFAULT '[]',
    state_version INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE room_map_state ADD COLUMN IF NOT EXISTS fog_regions JSONB NOT NULL DEFAULT '[]';
ALTER TABLE room_map_state ADD COLUMN IF NOT EXISTS token_visibility JSONB NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS character_map_positions (
    character_id TEXT NOT NULL,
    room_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (character_id, room_id)
);

CREATE TABLE IF NOT EXISTS encounters (
    encounter_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    type TEXT NOT NULL DEFAULT 'combat',
    status TEXT NOT NULL DEFAULT 'suggested',
    current_round INTEGER NOT NULL DEFAULT 0,
    summary TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS encounter_participants (
    encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
    character_id TEXT NOT NULL,
    side TEXT NOT NULL DEFAULT 'player',
    hp INTEGER NOT NULL DEFAULT 0,
    hp_max INTEGER NOT NULL DEFAULT 0,
    san INTEGER NOT NULL DEFAULT 0,
    san_max INTEGER NOT NULL DEFAULT 0,
    dex INTEGER NOT NULL DEFAULT 0,
    mov INTEGER NOT NULL DEFAULT 7,
    current_position TEXT DEFAULT '',
    distance_band TEXT NOT NULL DEFAULT 'medium',
    status_tags JSONB DEFAULT '[]',
    acted_this_round BOOLEAN NOT NULL DEFAULT FALSE,
    weapon_name TEXT DEFAULT '',
    damage_expression TEXT DEFAULT '1d3',
    main_skill TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    PRIMARY KEY (encounter_id, character_id)
);

CREATE TABLE IF NOT EXISTS encounter_pending_reactions (
    reaction_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
    source_action_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    attacker_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    attack_index INTEGER NOT NULL,
    attack_name TEXT NOT NULL,
    damage_expression TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    choice TEXT,
    result JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP,
    UNIQUE (encounter_id, character_id, round_number, attack_index)
);

CREATE INDEX IF NOT EXISTS idx_encounter_pending_reactions_character
    ON encounter_pending_reactions (room_id, character_id, status, created_at);

CREATE TABLE IF NOT EXISTS ai_call_logs (
    id BIGSERIAL PRIMARY KEY,
    room_id VARCHAR(64),
    action_id VARCHAR(64),
    task_type VARCHAR(32),
    provider VARCHAR(32),
    provider_order VARCHAR(128),
    duration_ms INTEGER,
    status VARCHAR(16),
    fallback_chain TEXT[],
    response_summary VARCHAR(256),
    input_tokens INTEGER,
    output_tokens INTEGER,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ai_provider_configs (
    provider_config_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    api_base_url TEXT NOT NULL,
    protocol TEXT NOT NULL,
    model TEXT NOT NULL,
    supports_image BOOLEAN NOT NULL DEFAULT FALSE,
    api_key_ciphertext TEXT NOT NULL,
    key_mask TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    test_status TEXT NOT NULL DEFAULT 'untested',
    last_tested_at TIMESTAMP,
    last_test_latency_ms INTEGER,
    created_by TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CHECK (protocol IN ('responses', 'chat_completions')),
    CHECK (test_status IN ('untested', 'passed', 'failed', 'key_unavailable'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_provider_configs_single_active
    ON ai_provider_configs(is_active) WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS ai_provider_config_audits (
    audit_id TEXT PRIMARY KEY,
    provider_config_id TEXT,
    action TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_provider_config_audits_created
    ON ai_provider_config_audits(created_at);

CREATE TABLE IF NOT EXISTS admin_data_purge_audits (
    audit_id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    target_count INTEGER NOT NULL DEFAULT 0,
    details JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL DEFAULT (NOW() + INTERVAL '365 days')
);

CREATE INDEX IF NOT EXISTS idx_admin_data_purge_audits_created
    ON admin_data_purge_audits(created_at);

CREATE TABLE IF NOT EXISTS spoiler_sensitive_items (
    item_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    category TEXT NOT NULL,
    label TEXT NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]',
    source_ref TEXT NOT NULL DEFAULT '',
    default_audience TEXT NOT NULL DEFAULT 'host',
    unlock_clue_ids JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_spoiler_items_scenario ON spoiler_sensitive_items(scenario_id, category);
ALTER TABLE spoiler_sensitive_items ADD COLUMN IF NOT EXISTS unlock_clue_ids JSONB NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS spoiler_audits (
    audit_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    action_id TEXT DEFAULT '',
    original_text TEXT NOT NULL,
    violations JSONB NOT NULL DEFAULT '[]',
    retry_count INTEGER NOT NULL DEFAULT 0,
    final_status TEXT NOT NULL DEFAULT 'blocked_fallback',
    final_text TEXT NOT NULL DEFAULT '',
    unlock_snapshot JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_spoiler_audits_room ON spoiler_audits(room_id, created_at);

ALTER TABLE ai_call_logs ADD COLUMN IF NOT EXISTS spoiler_review_status VARCHAR(32);
ALTER TABLE ai_call_logs ADD COLUMN IF NOT EXISTS spoiler_hit_items JSONB;
ALTER TABLE ai_call_logs ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;

CREATE TABLE IF NOT EXISTS character_profiles (
    profile_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    occupation TEXT DEFAULT '',
    attributes JSONB NOT NULL DEFAULT '{}',
    skills JSONB NOT NULL DEFAULT '{}',
    background TEXT DEFAULT '',
    backstory JSONB DEFAULT '{}',
    permanent_injuries JSONB DEFAULT '[]',
    permanent_insanities JSONB DEFAULT '[]',
    experience_points INTEGER DEFAULT 0,
    inheritable_items JSONB DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS character_runtime_state (
    character_id TEXT NOT NULL,
    room_id TEXT NOT NULL,
    profile_id TEXT,
    hp INTEGER NOT NULL DEFAULT 0,
    hp_max INTEGER NOT NULL DEFAULT 0,
    san INTEGER NOT NULL DEFAULT 0,
    san_max INTEGER NOT NULL DEFAULT 0,
    mp INTEGER NOT NULL DEFAULT 0,
    mp_max INTEGER NOT NULL DEFAULT 0,
    luck INTEGER NOT NULL DEFAULT 0,
    status_tags JSONB DEFAULT '[]',
    temp_modifiers JSONB DEFAULT '{}',
    visibility TEXT DEFAULT 'visible',
    version INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (character_id, room_id)
);

CREATE TABLE IF NOT EXISTS room_scene_state (
    room_id TEXT PRIMARY KEY REFERENCES rooms(room_id),
    current_scene TEXT DEFAULT '',
    visited_scenes JSONB DEFAULT '[]',
    triggered_triggers JSONB DEFAULT '[]',
    public_facts JSONB DEFAULT '[]',
    scene_variables JSONB DEFAULT '{}',
    current_bgm TEXT DEFAULT '',
    current_asset_url TEXT DEFAULT '',
    version INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE characters ADD COLUMN IF NOT EXISTS profile_id TEXT;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS integrity_status TEXT NOT NULL DEFAULT 'healthy';
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS integrity_reason TEXT;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS integrity_source TEXT;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS integrity_state_version INTEGER;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS integrity_updated_at TIMESTAMP;
ALTER TABLE events ADD COLUMN IF NOT EXISTS action_id TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS state_version INTEGER;
ALTER TABLE events ADD COLUMN IF NOT EXISTS payload_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE checkpoints ADD COLUMN IF NOT EXISTS schema_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE checkpoints ADD COLUMN IF NOT EXISTS state_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE checkpoints ADD COLUMN IF NOT EXISTS event_sequence BIGINT NOT NULL DEFAULT 0;
ALTER TABLE checkpoints ADD COLUMN IF NOT EXISTS snapshot_sha256 TEXT NOT NULL DEFAULT '';
ALTER TABLE checkpoints ADD COLUMN IF NOT EXISTS invariant_report JSONB NOT NULL DEFAULT '{}';
ALTER TABLE checkpoints ADD COLUMN IF NOT EXISTS verification_status TEXT NOT NULL DEFAULT 'unverified';
ALTER TABLE checkpoints ADD COLUMN IF NOT EXISTS checkpoint_type TEXT NOT NULL DEFAULT 'manual';
ALTER TABLE encounter_participants ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 0;
ALTER TABLE encounter_participants ADD COLUMN IF NOT EXISTS display_name TEXT DEFAULT '';
ALTER TABLE encounter_participants ADD COLUMN IF NOT EXISTS public_visibility TEXT NOT NULL DEFAULT 'hidden';
ALTER TABLE encounter_participants ADD COLUMN IF NOT EXISTS public_label TEXT DEFAULT '';
ALTER TABLE encounter_participants ADD COLUMN IF NOT EXISTS last_observed_position TEXT DEFAULT '';
ALTER TABLE clue_shares ADD COLUMN IF NOT EXISTS room_id TEXT;
ALTER TABLE encounters ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 0;
ALTER TABLE clues ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 0;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_events_room ON events(room_id, sequence);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_action ON events(action_id, sequence);

UPDATE character_templates AS template
SET attributes = COALESCE(template.attributes, '{}'::jsonb) ||
    '{"str": 50, "con": 50, "pow": 50, "dex": 60, "app": 60, "siz": 40, "int": 70, "edu": 80, "hp": 9, "san": 50, "luck": 50}'::jsonb
FROM scenarios AS scenario
WHERE template.scenario_id = scenario.scenario_id
  AND template.template_id = 'yhdx-reporter-v1'
  AND scenario.title = '向火独行'
  AND COALESCE(template.attributes, '{}'::jsonb) @> '{"hp": 11, "con": 55, "pow": 50, "san": 50, "luck": 50}'::jsonb
  AND NOT (
      COALESCE(template.attributes, '{}'::jsonb) ? 'str'
      OR COALESCE(template.attributes, '{}'::jsonb) ? 'STR'
  );
"""


class PgCursorWrapper:
    def __init__(self, cursor, auto_commit: bool = True):
        self._cursor = cursor
        self._auto_commit = auto_commit
        self._connection = cursor.connection
        self._lastrowid = None

    def execute(self, sql, params=None):
        translated = _coerce_jsonb_result_literals(_translate_sql(sql))
        params = self._coerce_params(translated, params)
        try:
            if params is not None:
                self._cursor.execute(translated, params)
            else:
                self._cursor.execute(translated)

            if self._auto_commit:
                self._connection.commit()
        except Exception:
            if self._auto_commit:
                try:
                    self._connection.rollback()
                except Exception:
                    pass
            raise
        return self

    def _coerce_params(self, sql, params=None):
        if params is None or not isinstance(params, (tuple, list)):
            return params
        values = list(params)
        lower_sql = sql.lower()
        boolean_columns = ("is_private", "is_ready", "is_secret")
        if any(column in lower_sql for column in boolean_columns):
            columns = self._insert_columns(lower_sql)
            for column in boolean_columns:
                if column in columns:
                    idx = columns.index(column)
                    if idx < len(values) and values[idx] in (0, 1):
                        values[idx] = bool(values[idx])
            if "set is_private = %s" in lower_sql and values and values[0] in (0, 1):
                values[0] = bool(values[0])
            if "set is_ready = %s" in lower_sql and values and values[0] in (0, 1):
                values[0] = bool(values[0])
            if "set is_secret = %s" in lower_sql and values and values[0] in (0, 1):
                values[0] = bool(values[0])
        if "result" in lower_sql:
            columns = self._insert_columns(lower_sql)
            if "result" in columns:
                idx = columns.index("result")
                if idx < len(values):
                    values[idx] = self._json_param(values[idx])
            elif "result = %s" in lower_sql:
                update_columns = self._update_columns(lower_sql)
                if "result" in update_columns:
                    idx = update_columns.index("result")
                    if idx < len(values):
                        values[idx] = self._json_param(values[idx])
        return tuple(values) if isinstance(params, tuple) else values

    def _insert_columns(self, sql: str) -> list[str]:
        match = re.search(r"insert\s+into\s+\w+\s*\(([^)]+)\)", sql)
        if not match:
            return []
        return [column.strip().strip('"') for column in match.group(1).split(",")]

    def _update_columns(self, sql: str) -> list[str]:
        match = re.search(r"update\s+\w+\s+set\s+(.+?)\s+where\s+", sql, re.DOTALL)
        if not match:
            return []
        assignments = match.group(1).split(",")
        return [
            assignment.split("=", 1)[0].strip().strip('"')
            for assignment in assignments
            if "=" in assignment and "%s" in assignment
        ]

    def _json_param(self, value):
        if value is None or not isinstance(value, str):
            return value
        try:
            json.loads(value)
            return value
        except Exception:
            return json.dumps(value, ensure_ascii=False)

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        if isinstance(row, (list, tuple)):
            if self._cursor.description:
                return {desc[0]: val for desc, val in zip(self._cursor.description, row)}
            return row
        return row

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows:
            return []
        first = rows[0]
        if isinstance(first, dict):
            return rows
        if isinstance(first, (list, tuple)) and self._cursor.description:
            return [
                {desc[0]: val for desc, val in zip(self._cursor.description, row)}
                for row in rows
            ]
        return rows

    @property
    def lastrowid(self):
        """Return the lastrowid value.

        For INSERT ... RETURNING queries, callers should use fetchone()
        directly instead of this property, as lastrowid does not consume
        RETURNING rows. Falls back to rowcount.
        """
        return self._lastrowid if self._lastrowid is not None else self._cursor.rowcount

    @property
    def rowcount(self):
        return self._cursor.rowcount


class PgConnection:
    def __init__(self, pool):
        self._pool = pool
        self._conn = None
        self._cursor = None

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = self._pool.getconn()
        return self._conn

    def execute(self, sql, params=None):
        conn = self._get_conn()
        if self._cursor is not None:
            self._cursor.close()
        cursor = conn.cursor()
        self._cursor = cursor
        wrapper = PgCursorWrapper(cursor, auto_commit=True)
        wrapper.execute(sql, params)
        return wrapper

    @contextmanager
    def transaction(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        wrapper = PgCursorWrapper(cursor, auto_commit=False)
        try:
            yield wrapper
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def executescript(self, sql):
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def commit(self):
        conn = self._get_conn()
        conn.commit()

    def close(self):
        if self._cursor is not None:
            try:
                self._cursor.close()
            except Exception:
                pass
            self._cursor = None
        if self._conn and not self._conn.closed:
            self._pool.putconn(self._conn)
            self._conn = None


class PgDatabase:
    def __init__(self, dsn: str = ''):
        self.dsn = dsn or 'postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper'
        self._pool = None

    def connect(self):
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2, maxconn=10, dsn=self.dsn,
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        return self._pool

    def get_connection(self) -> PgConnection:
        return PgConnection(self._pool)

    @contextmanager
    def get_conn(self):
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def initialize(self):
        with self.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)

    def close(self):
        if self._pool:
            self._pool.closeall()
