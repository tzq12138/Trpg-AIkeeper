# Product Document Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the seven brainstorming source documents and create one M0 normative document set with traceable ADR decisions.

**Architecture:** Store byte-for-byte historical evidence under `docs/90-归档`; place the only M0 normative definitions under `docs/00-产品规范`. Use ADR records and a decision map to connect the archival evidence to the effective rule without letting archival text define runtime behavior.

**Tech Stack:** Markdown, YAML front matter, SHA-256 manifests, repository-relative links.

## Global Constraints

- Do not alter source wording in the archival copies.
- `00-产品规范` is the only M0 normative entry point.
- M0 is `ai_only`; Engine is the only authority that writes runtime state.
- Shared Stage is optional and never blocks authoritative action completion.
- Do not claim implementation, testing, or production readiness merely because a document defines it.
- Do not commit this work unless the user explicitly asks for a commit.

---

### Task 1: Archive source evidence

**Files:**
- Create: `docs/90-归档/方向性问题头脑风暴/README.md`
- Create: `docs/90-归档/方向性问题头脑风暴/原始材料/*.md`

**Consumes:** Seven source files from `G:\hermes-agent-workplace\D&D\CodeX-aikeeper\docs\方向性问题头脑风暴`.

**Produces:** An immutable evidence set with file name, byte size, SHA-256 and archive-use rules.

- [ ] Add the seven source files as unchanged Markdown archive copies.
- [ ] Record each source file's byte length and SHA-256 in the archive README.
- [ ] State that archive files cannot be cited as current product definitions without an ADR or normative-document mapping.
- [ ] Verify the archive file count, hashes and byte lengths against the G-drive source directory.

### Task 2: Establish the normative entry point

**Files:**
- Create: `docs/00-产品规范/README.md`
- Create: `docs/00-产品规范/00-产品宪法.md`
- Create: `docs/00-产品规范/01-运行模式、角色与权限总表.md`
- Create: `docs/00-产品规范/02-核心用户旅程与生命周期.md`
- Create: `docs/00-产品规范/03-领域对象与唯一权威矩阵.md`

**Consumes:** The M0 plan and the 1–200 decision archive.

**Produces:** A single entry point that fixes product identity, roles, lifecycle terminology and write authority.

- [ ] Add shared YAML metadata to every normative document.
- [ ] Define the M0 product in the constitution without committing to out-of-scope long-term campaign or Human Keeper modes.
- [ ] Define `ScenarioPreparer`, `RoomOwner`, `TableSteward`, `Player`, `SharedStage`, `AIKeeper` and `Engine` as distinct concepts.
- [ ] Define `ScenarioPackage`, `Campaign`, `Room`, `Session`, `Scene`, `PlayerAction` and `ResolutionTransaction` once.
- [ ] Create a unique-authority matrix that prevents AI and projections from directly writing authoritative state.
- [ ] Verify the five files contain no competing `Host` definition and no Shared Stage acknowledgement dependency.

### Task 3: Define scope, safety and decision records

**Files:**
- Create: `docs/00-产品规范/04-M0范围、里程碑与指标.md`
- Create: `docs/00-产品规范/05-跨域安全与非功能基线.md`
- Create: `docs/00-产品规范/06-决策记录 ADR.md`
- Create: `docs/00-产品规范/ADR/ADR-001-ai-only-m0.md` through `ADR-008-m0-short-module.md`
- Create: `docs/00-产品规范/ADR/裁决映射.md`

**Consumes:** M0 gates, fixed decisions and decision records 1–200.

**Produces:** A release scope, non-functional floor and traceable status for every decision range.

- [ ] Separate M0 gate requirements from non-gating retained features and Later work.
- [ ] Define privacy, content safety, accessibility, performance, cost, recovery and audit boundaries without claiming code coverage.
- [ ] Write ADR-001 through ADR-008 with context, alternatives, decision, consequences and superseded wording.
- [ ] Map each decision range from 1–200 to one of `adopted`, `amended`, `archived` or `later`, with a source link and an effective normative target.
- [ ] Verify that every M0 fixed decision is represented exactly once by an ADR and that every archived decision range has an effective-status label.

### Task 4: Validate navigation and provenance

**Files:**
- Modify: `docs/README.md`
- Modify: `docs/00-产品规范/README.md`
- Modify: `docs/90-归档/方向性问题头脑风暴/README.md`

**Consumes:** The archive manifest and normative document set.

**Produces:** A documented reading path and a static validation result.

- [ ] Add a concise top-level route from `docs/README.md` to the normative entry point and archive evidence.
- [ ] Check every Markdown link under the two new document trees resolves to a tracked local file.
- [ ] Recompute the archive hashes and compare them to the manifest.
- [ ] Run `git diff --check` and record the documentation-only verification result.
