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
    owner_token TEXT NOT NULL,
    owner_account_id TEXT,
    status TEXT NOT NULL DEFAULT 'lobby',
    spoiler_level TEXT DEFAULT 'standard',
    state_version INTEGER NOT NULL DEFAULT 0,
    player_experience_version TEXT NOT NULL DEFAULT 'v2',
    action_pacing_preset TEXT NOT NULL DEFAULT 'standard',
    action_timing JSONB NOT NULL DEFAULT '{"input_hint_seconds":60,"receipt_seconds":5,"preview_seconds":30,"resolution_seconds":180}'::jsonb,
    draft_analysis_enabled BOOLEAN NOT NULL DEFAULT TRUE,
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
    controller_device_id TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (room_id, character_id)
);

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
    visibility TEXT NOT NULL DEFAULT 'party',
    source TEXT NOT NULL DEFAULT 'player',
    confirmed_by TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evidence_cards_room_visibility
    ON evidence_cards(room_id, visibility, updated_at DESC);

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
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP,
    summary TEXT
);

ALTER TABLE actions ADD COLUMN IF NOT EXISTS turn_id TEXT;

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
ALTER TABLE characters ADD COLUMN IF NOT EXISTS account_id TEXT;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'player';
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS owner_account_id TEXT;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS player_experience_version TEXT NOT NULL DEFAULT 'v1';
ALTER TABLE rooms ALTER COLUMN player_experience_version SET DEFAULT 'v2';
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS action_pacing_preset TEXT NOT NULL DEFAULT 'standard';
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS action_timing JSONB NOT NULL DEFAULT '{"input_hint_seconds":60,"receipt_seconds":5,"preview_seconds":30,"resolution_seconds":180}'::jsonb;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS draft_analysis_enabled BOOLEAN NOT NULL DEFAULT TRUE;
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

CREATE TABLE IF NOT EXISTS spoiler_sensitive_items (
    item_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    category TEXT NOT NULL,
    label TEXT NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]',
    source_ref TEXT NOT NULL DEFAULT '',
    default_audience TEXT NOT NULL DEFAULT 'host',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_spoiler_items_scenario ON spoiler_sensitive_items(scenario_id, category);

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
ALTER TABLE encounter_participants ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 0;
ALTER TABLE encounter_participants ADD COLUMN IF NOT EXISTS display_name TEXT DEFAULT '';
ALTER TABLE clue_shares ADD COLUMN IF NOT EXISTS room_id TEXT;
ALTER TABLE encounters ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 0;
ALTER TABLE clues ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 0;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_events_room ON events(room_id, sequence);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
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
