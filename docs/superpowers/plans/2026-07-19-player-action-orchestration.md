# Player Action Orchestration and Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the four `docs/260718` designs as one evidence-safe player-action runtime: player intent is confirmed and resolved by the server, all views derive from one committed result, and public stage, player, and Host Console remain physically separated.

**Architecture:** Keep the existing V2 draft/action/state chain as the persistence and CoC7 execution base. Add an explicit protocol layer before it (`PlayerActionEnvelope → IntentContract → ExecutionPolicy`) and a committed-result layer after it (`ResolutionBundle → projections → presentation release`). Build the responsive player information architecture and the combat declaration runtime on those contracts rather than adding another parallel action path.

**Tech Stack:** FastAPI, Pydantic, PostgreSQL/pgvector, existing `StateService` and CoC7 rules, WebSocket event registry, React/Vite/TypeScript, pytest and Vitest.

## Global Constraints

- Work in `G:\hermes-agent-workplace\D&D\CodeX-aikeeper` on the user-selected `main` workspace; do not reset, clean, or alter unrelated dirty files.
- Preserve raw player input, server-derived identity, idempotency, `stateVersion`, citations, and room sequence in every formal action trace.
- AI may interpret, suggest mechanics, and narrate only; it must never become the source of dice, rule values, state mutation, visibility, or release decisions.
- New rooms use the new protocol. Existing rooms retain read/reconnect compatibility only until their archived state is migrated deliberately.
- Public Stage receives public-safe projections only. Host Console, player-private results, audit traces, and raw provider data never share a DTO or endpoint.
- Follow test-first delivery: run the new targeted test red before each production change, then the focused suite green.

---

## Requirement Traceability

| Source | Deliverable | Acceptance evidence |
| --- | --- | --- |
| `AIKP … 完整协议` + PRD §9–27 | Envelope, input modes, intent confirmation, state-first bundle, release/reconnect | protocol pytest suite and WebSocket contract assertions |
| `Round1` | Current-task mobile screen, investigation, character/inventory, public stage | Vitest + 360/390/430 browser captures |
| `Round2` | Round declaration state machine, absence/reconnect rules, public combat projection | encounter pytest + 4-player browser run |
| PRD §23–24 | Viewer-filtered AI context, no leak, fallbacks/replay | spoiler/provider/projection tests |

## Delivery Sequence

### Task 1: Formal action intake and intent contract

**Files:**
- Create: `src/server/engine/action_protocol.py`
- Modify: `src/server/models.py`, `src/server/db_adapter.py`, `src/server/db_pg.py`, `src/server/player/router_actions_v2.py`, `src/server/player/action_service.py`
- Test: `tests/server/test_player_action_protocol.py`

**Interfaces:**
- Consumes: authenticated character from `_require_character`, current room `state_version`, draft analysis gateway.
- Produces: `PlayerActionEnvelopeDTO`, `ActionReceiptDTO`, `IntentContractDTO`, and an immutable action-envelope audit row.

- [ ] Write tests that reject forged actor/skill/roll fields, accept the ten explicit input modes, preserve raw text, return `received` before AI, and return the original receipt on duplicate `actionId`.
- [ ] Run `python -m pytest tests/server/test_player_action_protocol.py -q` and confirm each new test fails because the protocol endpoint/contracts do not exist.
- [ ] Add strict Pydantic contracts and `POST /api/player/actions/intake`; derive actor and room from token, validate `baseStateVersion`, persist the envelope, and route non-state modes away from Rule/State.
- [ ] Make existing draft confirmation create a protocol envelope rather than a second independent action record.
- [ ] Re-run `python -m pytest tests/server/test_player_action_protocol.py tests/server/test_action_drafts_v2.py -q`.

### Task 2: Server-owned policy, safe AI context, and clarification

**Files:**
- Modify: `src/server/ai/gateway.py`, `src/server/player/action_service.py`, `src/server/engine/action_protocol.py`, `src/server/ai/spoiler_control.py`
- Test: `tests/server/test_player_action_protocol.py`, `tests/server/test_spoiler.py`

**Interfaces:**
- Consumes: `PlayerActionEnvelopeDTO` and a viewer-filtered runtime view.
- Produces: `IntentContractDTO` with target, method, constraints, resources, conditions, ambiguity, visibility, citations, and server-selected confirmation policy.

- [ ] Add failing tests proving truth/endings/undiscovered clues/other players' private data never enter the compiler context, ambiguous high-impact targets require clarification, and AI cannot lower local risk.
- [ ] Implement context construction from character/scene/inventory/knowledge projections; preserve local deterministic fallback and return a structured manual-selection fallback on provider failure.
- [ ] Re-run focused protocol and spoiler suites.

### Task 3: Resolution bundle, atomic commit, and release gate

**Files:**
- Create: `src/server/engine/resolution_contract.py`
- Modify: `src/server/engine/resolution_pipeline.py`, `src/server/engine/state_service.py`, `src/server/engine/action_lifecycle.py`, `src/server/db_adapter.py`, `src/server/db_pg.py`
- Test: `tests/server/test_resolution_bundle.py`, `tests/server/test_action_lifecycle_v2.py`

**Interfaces:**
- Consumes: confirmed action, authoritative Rule result, applied `StateChangeSet`.
- Produces: one persisted `ResolutionBundle` with public/private/host facts, source refs, transaction id, versions, release status, and replay id.

- [ ] Write failing tests that state failure emits no success narrative or completed event; projection failure replays without a second roll/mutation; one bundle derives all projections; and no mutation is placed in a Stage payload.
- [ ] Implement bundle construction only after successful `StateService.apply_change`; record no-op rule outcomes without incrementing state version.
- [ ] Implement release state (`closed → eligible → released`) and immutable presentation/replay records.
- [ ] Re-run resolution, lifecycle, and protocol suites.

### Task 4: Projection boundary and Host presentation separation

**Files:**
- Modify: `src/server/engine/projection.py`, `src/server/events/events_registry.py`, `src/server/models.py`, `src/server/host/router_host.py`, `src/server/host/host_store.py`
- Create: `src/server/host/router_console.py`, `src/client/src/pages/HostConsole.tsx`, `src/client/src/pages/hostConsoleApi.ts`
- Modify: `src/client/src/pages/HostStage.tsx`, `src/client/src/shared/types.ts`
- Test: `tests/server/test_host_projection_boundary.py`, `tests/server/test_events_bus.py`

**Interfaces:**
- Consumes: committed `ResolutionBundle` and release status.
- Produces: `HostRevealTransactionDTO`, `PlayerResolutionReceiptDTO`, `PublicObservationDTO`, and a Host-only review packet.

- [ ] Write failing tests that the Stage endpoint/event cannot include private patches, hidden difficulty, raw prompts, or keeper notes; Host ACK can only advance a presentation step; Player A private results never reach Player B.
- [ ] Split Stage and Console routes/DTOs; project public narrative after `SpoilerGuard`; provide a Console-only audited review backlog.
- [ ] Re-run host/projection/event suites and build the frontend.

### Task 5: Player current-task interface and responsive information model

**Files:**
- Create: `src/client/src/components/player/CurrentTaskPanel.tsx`, `src/client/src/components/player/InputModeComposer.tsx`, `src/client/src/components/player/ResultReceiptCard.tsx`
- Modify: `src/client/src/pages/PlayerActionPage.tsx`, `src/client/src/components/PlayerTerminal.tsx`, `src/client/src/shared/player-api.ts`, `src/client/src/shared/types.ts`, client styles
- Test: `src/client/src/components/player/*.test.tsx`

**Interfaces:**
- Consumes: protocol receipt, clarification/confirmation events, reconnect state, player projections.
- Produces: one highest-priority current item, explicit input mode, risk-appropriate confirmation, private/public result cards, and a mobile drawer for pending/recent work.

- [ ] Write failing Vitest cases for explicit mode retention, chat/OOC not creating actions, low-risk undo window, high-risk confirmation, and private receipt not entering public message list.
- [ ] Replace the generic tactical terminal as the primary action UI; preserve map and item actions by filling natural-language action input rather than mutating state directly.
- [ ] Verify `npm run test -- --run` and `npm run build`.

### Task 6: Investigation, character, inventory, and public-stage information architecture

**Files:**
- Create focused components under `src/client/src/components/player/` for investigation, clues, hypotheses, evidence, item transfer, and character exceptions.
- Modify: `PlayerCharacter.tsx`, `PlayerInventory.tsx`, `PlayerActionPage.tsx`, `HostStage.tsx`, map projection endpoints.
- Test: matching Vitest files and `tests/server/test_campaign_v2.py` additions.

- [ ] Add failing tests for observed/testimony/guess/disputed/confirmed/debunked labels; private-by-default hypotheses; explicit clue share; request/confirm/atomic item transfer; and no precision private stat display on public stage.
- [ ] Implement the player four-tab model (current, investigation, character, more), player-safe semantic map, and screen-reader-safe status/notification priority.
- [ ] Verify mobile widths 360/390/430px in browser and capture screenshots.

### Task 7: Combat declaration runtime

**Files:**
- Create: `src/server/engine/encounter_runtime.py`
- Modify: `src/server/encounter_persistence.py`, `src/server/rules/encounter_handlers.py`, `src/server/player/router_actions_v2.py`, host encounter routes, event registry, player/host components.
- Test: `tests/server/test_encounter_runtime.py`, client combat component tests.

**Interfaces:**
- Consumes: submitted combat envelopes and authoritative encounter snapshot.
- Produces: `ROUND_PREPARE → DECLARATION_OPEN → LOCKED → VISIBLE_PREPARATION → PLANNING → RESOLVING → SUMMARY` events and a round `ResolutionBundle`.

- [ ] Write failing tests for one editable declaration per active player, max two perceived targets, no dice/resource/move before lock, global rule order over submit order, absence restrictions, reconnect spectator rule, and no hidden enemy leakage.
- [ ] Implement declaration lock, director plan validation, deterministic per-step commits, and public-only round summary.
- [ ] Re-run encounter/action/projection suites and a 1 Host + 4 Player browser scenario.

### Task 8: Maps, handouts, media, and accessibility-safe stage behavior

**Files:**
- Modify: `src/server/maps_router.py`, scenario content projection, relevant player map and Host stage components.
- Test: map projection and client map tests.

- [ ] Write failing tests for semantic-map fog, click-to-fill-only movement, public-safe handout/media visibility, and text scene fallback.
- [ ] Implement safe known-place/known-connection projections plus persistent handouts, safety warnings, and group-decision cards.
- [ ] Verify desktop stage and mobile map browser flows.

### Task 9: Recovery, audit, and acceptance harness

**Files:**
- Modify: reconnect/router archive/event log services and admin acceptance pages.
- Create: `docs/260718/AIKP_RUNTIME_ACCEPTANCE_REPORT.md`, deterministic provider fixtures, and browser test script/report fixtures.
- Test: reconnect, duplicate-event, provider-fallback, archive, and end-to-end tests.

- [ ] Add failing tests for reconnect pending/completed action recovery, replay-only projection, ACK resume without duplicates, full trace links, and provider fallback distinguishable from in-world failure.
- [ ] Implement recovery projection replay and a repeatable 1 Host + 4 Player acceptance flow using a deterministic provider plus text-only fallback.
- [ ] Run backend full pytest, client Vitest, Vite build, `git diff --check`, browser flows, and write exact pass/fail evidence in the acceptance report.

## Execution Checkpoints

1. After Tasks 1–4: protocol P0 is authoritative and leak-safe.
2. After Tasks 5–6: the player/public/Host experiences consume only those contracts.
3. After Tasks 7–8: combat and map behavior obey the same contract.
4. After Task 9: automated and browser evidence covers all four source documents before any claim of completion.
