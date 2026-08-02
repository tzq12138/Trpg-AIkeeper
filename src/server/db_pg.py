import psycopg2
import psycopg2.pool
import psycopg2.extras
from contextlib import contextmanager
import logging

from .db_adapter import SCHEMA_SQL as SHARED_SCHEMA_SQL

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rooms (
    room_id TEXT PRIMARY KEY,
    scenario_id TEXT,
    scenario_version_id TEXT,
    runtime_package_version_id TEXT,
    owner_token TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'lobby',
    spoiler_level TEXT DEFAULT 'standard',
    state_version INTEGER NOT NULL DEFAULT 0,
    player_experience_version TEXT NOT NULL DEFAULT 'v2',
    action_pacing_preset TEXT NOT NULL DEFAULT 'standard',
    action_timing JSONB NOT NULL DEFAULT '{"input_hint_seconds":60,"receipt_seconds":5,"preview_seconds":30,"resolution_seconds":180}'::jsonb,
    draft_analysis_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    speech_routing TEXT NOT NULL DEFAULT 'party_message',
    risk_contract JSONB,
    risk_contract_version TEXT,
    risk_contract_hash TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS characters (
    character_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    player_name TEXT NOT NULL,
    player_token TEXT NOT NULL,
    xlsx_data JSONB,
    is_ready BOOLEAN NOT NULL DEFAULT FALSE
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

CREATE INDEX IF NOT EXISTS idx_action_drafts_character_status
    ON action_drafts(character_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_action_status_events_action
    ON action_status_events(action_id, status_event_id);
CREATE INDEX IF NOT EXISTS idx_action_reviews_status
    ON action_review_requests(status, created_at);

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

CREATE INDEX IF NOT EXISTS idx_chunks_source ON document_chunks(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_chunks_room ON document_chunks(room_id);
CREATE INDEX IF NOT EXISTS idx_scenario_versions_scenario_status ON scenario_versions(scenario_id, status);

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

ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS scenario_assets JSONB;
CREATE TABLE IF NOT EXISTS scenario_assets (
    asset_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    file_size INTEGER NOT NULL DEFAULT 0,
    relative_path TEXT NOT NULL,
    visibility TEXT DEFAULT 'host_only',
    source_document_id TEXT REFERENCES source_documents(source_document_id),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
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
ALTER TABLE actions ADD COLUMN IF NOT EXISTS turn_id TEXT;
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
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS player_experience_version TEXT NOT NULL DEFAULT 'v1';
ALTER TABLE rooms ALTER COLUMN player_experience_version SET DEFAULT 'v2';
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS action_pacing_preset TEXT NOT NULL DEFAULT 'standard';
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS action_timing JSONB NOT NULL DEFAULT '{"input_hint_seconds":60,"receipt_seconds":5,"preview_seconds":30,"resolution_seconds":180}'::jsonb;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS draft_analysis_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS speech_routing TEXT NOT NULL DEFAULT 'party_message';
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
"""

SCHEMA_SQL = SHARED_SCHEMA_SQL


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
