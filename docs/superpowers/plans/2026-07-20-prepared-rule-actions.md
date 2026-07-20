# Prepared Rule Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a confirmed player preparation arm one safe reaction that is executed only by a matching deterministic public rule event.

**Architecture:** A preparation remains an ordinary high-risk action draft until confirmation, then persists as an `armed` record without applying world state. The resolution pipeline emits a sanitized, whitelisted rule event after an authoritative action resolves; the prepared-action service atomically consumes at most one matching record and creates a normal queued action for the existing rule pipeline.

**Tech Stack:** FastAPI, PostgreSQL, Pydantic, pytest, existing action draft and resolution pipeline.

## Global Constraints

- Only these trigger kinds exist in this iteration: `enemy_public_attack_declared`, `enemy_enters_melee_range`, `ally_publicly_hurt`, and `combat_started`.
- A Host, AI response, narration text, map click, or arbitrary client payload cannot trigger a preparation.
- The reaction is a fixed safe action (`take_cover`, `withdraw`, or `protect_ally`) with no hidden target discovery and no direct state patch.
- Arming, triggering, expiration, and consumption are auditable; a record is consumed at most once.
- Keep both schema initialization paths in sync: `src/server/db_adapter.py` and `src/server/db_pg.py`.
- Do not commit or clean the shared dirty workspace.

---

### Task 1: Persist and validate an armed preparation

**Files:**
- Modify: `src/server/models.py`
- Modify: `src/server/player/action_service.py`
- Modify: `src/server/db_adapter.py`
- Modify: `src/server/db_pg.py`
- Test: `tests/server/test_prepared_rule_actions.py`

**Interfaces:**
- Produces `intent_type="prepared_action"` drafts whose params contain `triggerKind` and `reactionKind`.
- Produces `armed_prepared_actions` rows with `status` of `armed`, `triggered`, `completed`, `canceled`, or `expired`.

- [ ] **Step 1: Write the failing validation and persistence tests**

```python
def test_prepared_action_requires_whitelisted_trigger_and_safe_reaction():
    draft = analyze_action_draft(ActionDraftAnalyzeRequest(
        declared_intent="敌人公开攻击时我躲到柱子后",
        intent_type="prepared_action",
        params={"triggerKind": "enemy_public_attack_declared", "reactionKind": "take_cover"},
    ))
    assert draft.requires_confirmation is True
    assert draft.params["triggerKind"] == "enemy_public_attack_declared"

def test_confirmed_prepared_action_arms_without_queued_action(client, test_db):
    # Confirm one draft and assert an armed record exists while no reaction action is queued.
```

- [ ] **Step 2: Run the focused tests and verify they fail because the intent and table do not exist**

Run: `python -m pytest tests/server/test_prepared_rule_actions.py -q`

- [ ] **Step 3: Add the smallest schema, model, analysis, and confirmation implementation**

```python
PREPARED_TRIGGER_KINDS = frozenset({"enemy_public_attack_declared", ...})
PREPARED_REACTION_KINDS = frozenset({"take_cover", "withdraw", "protect_ally"})

def arm_prepared_action(tx, character, action_id, params):
    # Insert one immutable armed record; no state service call and no reaction action.
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `python -m pytest tests/server/test_prepared_rule_actions.py -q`

### Task 2: Consume only authoritative rule events

**Files:**
- Create: `src/server/engine/prepared_rule_actions.py`
- Modify: `src/server/engine/resolution_pipeline.py`
- Modify: `src/server/player/router_player.py`
- Modify: `src/server/events/events_registry.py`
- Test: `tests/server/test_prepared_rule_actions.py`

**Interfaces:**
- Consumes `consume_prepared_actions_for_rule_event(conn, room_id, source_action_id, rule_event)`.
- Produces one ordinary queued action per matching armed preparation and returns player-safe projections.

- [ ] **Step 1: Write failing trigger tests**

```python
def test_matching_authoritative_event_consumes_once_and_queues_reaction(test_db):
    triggered = consume_prepared_actions_for_rule_event(
        test_db, room_id="room-1", source_action_id="attack-1",
        rule_event={"kind": "enemy_public_attack_declared", "visibility": "public"},
    )
    assert [item["reaction_kind"] for item in triggered] == ["take_cover"]

def test_private_or_unlisted_event_cannot_trigger_prepared_action(test_db):
    assert consume_prepared_actions_for_rule_event(...) == []
```

- [ ] **Step 2: Run the focused tests and verify they fail because the service is missing**

Run: `python -m pytest tests/server/test_prepared_rule_actions.py -q`

- [ ] **Step 3: Implement atomic consumption and emit player-safe lifecycle events**

```python
def consume_prepared_actions_for_rule_event(conn, room_id, source_action_id, rule_event):
    # Validate the internal event first, lock armed rows, mark each triggered,
    # insert a standard queued action, then return only owner-facing summaries.
```

- [ ] **Step 4: Wire only rule-engine outputs to the consumer and run focused tests**

Run: `python -m pytest tests/server/test_prepared_rule_actions.py tests/server/test_resolution_pipeline.py -q`

### Task 3: Preserve replay, expiry, and projection safety

**Files:**
- Modify: `src/server/player/action_service.py`
- Modify: `src/server/player/router_player.py`
- Test: `tests/server/test_prepared_rule_actions.py`

**Interfaces:**
- A duplicate source event never queues a second reaction.
- Expired armed records are marked `expired` and are omitted from player projections.

- [ ] **Step 1: Write failing duplicate, expiry, and non-owner visibility tests**

```python
def test_duplicate_source_event_does_not_queue_a_second_reaction(test_db):
    assert len(consume_prepared_actions_for_rule_event(...)) == 1
    assert consume_prepared_actions_for_rule_event(...) == []

def test_other_players_cannot_read_an_armed_preparation(client):
    assert client.get("/api/player/prepared-actions", headers=other_headers).json() == []
```

- [ ] **Step 2: Run the focused tests and verify they fail for the absent projection/expiry behavior**

Run: `python -m pytest tests/server/test_prepared_rule_actions.py -q`

- [ ] **Step 3: Add expiry cleanup and owner-only read projection**

```python
def list_owned_prepared_actions(conn, character_id):
    # Transition stale armed rows to expired, then return owner-safe status only.
```

- [ ] **Step 4: Run focused and adjacent regression suites**

Run: `python -m pytest tests/server/test_prepared_rule_actions.py tests/server/test_action_drafts_v2.py tests/server/test_resolution_pipeline.py -q`

### Task 4: Record verification evidence

**Files:**
- Modify: `docs/260718_IMPLEMENTATION_MATRIX_2026-07-19.md`
- Modify: `docs/260718_COMPLETION_AUDIT_2026-07-19.md`
- Modify: `docs/loop_runs/2026-07-20-collaboration-dependency-regression.md`

- [ ] **Step 1: Run backend and frontend validation**

Run: `python -m pytest tests/server -q`; `cd src/client && npm run test -- --run`; `cd src/client && npm run build`; `git diff --check`

- [ ] **Step 2: Record only observed outcomes and retain browser/provider gates as pending until a freshly restarted service is inspected**
