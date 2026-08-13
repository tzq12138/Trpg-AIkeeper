# 权威 CoC7 RAG 与房间分页管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用经过页级校验的 380 页 CoC7 核心规则书替换不可靠的 25 页测试规则，阻断旧规则运行时访问，并为管理员提供审计与房间分页批量删除能力。

**Architecture:** 在既有版本化 RAG 表上增加“权威来源页”和“版本发布门槛”记录；RAG 查询只允许已发布且合格的版本，并按页写入引用。房间用独立的规则来源状态阻断旧版本入口，AI-KP 在无规则证据时复用房间局部的临时裁定。房间列表采用服务端分页，现有批量删除端点继续逐项事务处理。

**Tech Stack:** Python 3、FastAPI、PostgreSQL/pgvector、pdfplumber、pytest、React、TypeScript、Vitest、Vite。

## Global Constraints

- 唯一正式来源为 `COC7th核心规则书v1.2.1.pdf`，页数必须为 `380`，SHA-256 必须为 `22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815`。
- 不物理删除旧 25 页测试规则、测试脚本或素材；只隔离其运行时使用并标记受影响房间。
- 规则原文、页码、来源指纹、检索得分及临时裁定只允许管理员审计接口读取；房主和玩家不得读取。
- 所有新规则分块必须属于单一物理页，并带 `source_document_id`、`source_part_id`、真实 `page_number` 和页内范围。
- 任何规则检索入口只允许 `status='published'` 且 `runtime_eligible=TRUE` 的规则版本；传入版本 ID 不能绕过。
- 低相关或无依据的规则查询不得返回无关规则；AI-KP 可以继续叙事，但不得伪造规则出处或页码。
- 房间依赖已隔离的旧规则时显示稳定的 `rule_source_retired` 结果并不可打开；不自动迁移或复活旧房间。
- 房间分页每页仅允许 `10`、`30`、`50`；全选只作用当前页，切页/改每页数量清空选择。
- 批量删除必须保留前端可见确认和 `{ ids, confirm: true }` 后端确认；前端只移除真实删除成功的对象。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `src/server/db_adapter.py` | 增量 schema：规则来源页、发布门槛、房间规则状态、临时裁定与索引。 |
| `src/server/rules/authoritative_coc7.py` | 固定来源规格、文件验证、页级提取/分类、导入与发布门槛计算。 |
| `src/server/ai/rag.py` | 页级规则索引、合格版本过滤、中文词法候选和规则最低相关性门槛。 |
| `src/server/rag_router.py` | 管理员导入、审计、审核、隔离接口；发布与搜索路径资格保护。 |
| `src/server/rule_source_lifecycle.py` | 解析有效规则版本、隔离旧版、房间失效检查和临时裁定持久化。 |
| `src/server/router_rooms.py`、`src/server/player/auth.py`、`src/server/host/router_host.py` | 房间创建绑定正式规则，玩家/房主入口阻断失效房间。 |
| `src/server/ai/ai_kp.py`、`src/server/ai/rag_context.py` | 在无规则证据时读取/保存当前房间局部临时裁定，且只交给 AI。 |
| `src/server/router_admin.py` | 房间分页响应和参数验证。 |
| `src/client/src/pages/AdminDashboard.tsx` | 房间分页控件、当前页全选和删除后的页码恢复。 |
| `src/client/src/pages/AdminDashboard.test.tsx` | 分页纯函数和批量删除选择行为的 Vitest 回归测试。 |
| `tests/server/test_authoritative_coc7.py` | 来源指纹、页级导入、门槛和隔离测试。 |
| `tests/server/test_rag_search.py`、`tests/server/test_rag_router.py` | 检索资格、中文词法召回、低相关拒答和管理员审计 API。 |
| `tests/server/test_rooms.py`、`tests/server/test_room_rule_source_lifecycle.py` | 新房间绑定与旧房间不可打开、局部临时裁定。 |
| `tests/server/test_admin_room_pagination.py` | 10/30/50 分页、边界和现有列表兼容性。 |

## Task 1: 规则来源状态与数据库最小模型

**Files:**
- Create: `src/server/rules/authoritative_coc7.py`
- Create: `src/server/rule_source_lifecycle.py`
- Modify: `src/server/db_adapter.py`
- Create: `tests/server/test_authoritative_coc7.py`

**Interfaces:**
- Produces `OfficialRulebookSpec`, `validate_official_rulebook_bytes`, `RuleSourcePage`, `authoritative_gate_snapshot`。
- Produces `current_authoritative_base_version(conn) -> str | None`、`ensure_room_rule_source_available(conn, room_id)`、`retire_local_test_rule_versions(conn) -> dict[str, int]`。
- Consumed by importer, RAG store, room routers and admin audit endpoints.

- [ ] **Step 1: 写入失败的 schema/来源测试**

```python
def test_authoritative_rulebook_rejects_wrong_hash_and_page_count(tmp_path):
    source = tmp_path / "wrong.pdf"
    source.write_bytes(b"not the official rulebook")

    with pytest.raises(AuthoritativeRulebookError, match="sha256"):
        validate_official_rulebook_path(source)


def test_rule_source_schema_stores_one_status_for_each_physical_page(test_db):
    test_db.execute("INSERT INTO source_documents (...) VALUES (...)")
    test_db.execute("INSERT INTO rule_source_pages (...) VALUES (..., 1, 'indexable', ...)")
    assert test_db.execute("SELECT extraction_status FROM rule_source_pages").fetchone()["extraction_status"] == "indexable"
```

- [ ] **Step 2: 运行测试确认失败原因是缺少 API/schema**

Run: `python -m pytest tests/server/test_authoritative_coc7.py -q`

Expected: FAIL，缺少 `AuthoritativeRulebookError` 或 `rule_source_pages` 表，而不是数据库连接错误。

- [ ] **Step 3: 增加增量 schema 和来源规格**

在共享 `SCHEMA_SQL` 末尾增加幂等 DDL：

```sql
ALTER TABLE rule_set_versions
  ADD COLUMN IF NOT EXISTS runtime_eligible BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE rooms
  ADD COLUMN IF NOT EXISTS rule_source_status TEXT NOT NULL DEFAULT 'ready';
ALTER TABLE rooms
  ADD COLUMN IF NOT EXISTS rule_source_reason TEXT;

CREATE TABLE IF NOT EXISTS rule_source_pages (
  rule_source_page_id TEXT PRIMARY KEY,
  source_document_id TEXT NOT NULL REFERENCES source_documents(source_document_id),
  page_number INTEGER NOT NULL,
  extraction_status TEXT NOT NULL,
  text_sha256 TEXT NOT NULL,
  extraction_method TEXT NOT NULL,
  reviewed_by TEXT,
  reviewed_at TIMESTAMP,
  diagnostics JSONB NOT NULL DEFAULT '{}',
  UNIQUE (source_document_id, page_number)
);
```

同时创建 `rule_version_publication_gates` 与 `room_rule_adjudications`，并为 `rooms(rule_source_status)`、`rule_source_pages(source_document_id, page_number)`、`document_chunks(rule_set_version_id, source_part_id)` 增加索引。规则来源模块必须只接受固定文件名、页数和 SHA-256；找不到或不匹配时抛出可审计错误，绝不猜测来源。

- [ ] **Step 4: 运行 Task 1 测试确认通过**

Run: `python -m pytest tests/server/test_authoritative_coc7.py -q`

Expected: PASS。

- [ ] **Step 5: 提交 Task 1**

```bash
git add src/server/db_adapter.py src/server/rules/authoritative_coc7.py src/server/rule_source_lifecycle.py tests/server/test_authoritative_coc7.py
git commit -m "feat: add authoritative CoC7 source model"
```

## Task 2: 页级导入、发布门槛与管理员审计

**Files:**
- Modify: `src/server/rules/authoritative_coc7.py`
- Modify: `src/server/ai/rag.py`
- Modify: `src/server/rag_router.py`
- Modify: `tests/server/test_authoritative_coc7.py`
- Modify: `tests/server/test_rag_router.py`

**Interfaces:**
- Consumes `OfficialRulebookSpec`、`rule_source_pages` 和 `RAGStore` embedding。
- Produces `import_authoritative_coc7(conn, rag, actor_id) -> dict`、`approve_rule_source_review(conn, version_id, actor_id) -> dict`、`get_rule_version_audit(conn, version_id) -> dict`。
- Produces `RAGStore.index_rule_pages(...) -> int`；每个 chunk 的 citation 必须含真实页码。

- [ ] **Step 1: 写入失败的页级导入/审计测试**

```python
def test_import_indexes_only_page_bound_chunks_and_records_all_pages(client, test_db, monkeypatch):
    imported = import_authoritative_coc7(test_db, FakeRag(), actor_id="acc-admin")
    assert imported["page_count"] == 380
    assert imported["gate_status"] in {"pending_review", "ready"}
    assert test_db.execute(
        "SELECT COUNT(*) AS n FROM rule_source_pages WHERE source_document_id = %s",
        (imported["source_document_id"],),
    ).fetchone()["n"] == 380


def test_publish_rejects_unreviewed_or_incomplete_authoritative_version(client, test_db):
    response = client.post(f"/api/rag/rule-set-versions/{version_id}/publish", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "rule_version_gate_not_ready"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/server/test_authoritative_coc7.py tests/server/test_rag_router.py -q`

Expected: FAIL，导入器、门槛或审计端点尚不存在。

- [ ] **Step 3: 实现受控页级导入和索引**

`import_authoritative_coc7` 必须：

1. 读取固定来源并验证 SHA-256 与 380 页；
2. 将每一物理页写入 `source_parts` 和 `rule_source_pages`，保留页码、文本哈希、提取方法与状态；
3. 对空白封面、版权、目录、索引、空白表单写 `archived_non_retrieval`，无法可靠提取的页写 `needs_review`；
4. 仅将 `indexable` 页交给 `index_rule_pages`；每块都限制在本页文本范围；
5. 创建 draft 规则版本和 `rule_version_publication_gates`，不自动发布；
6. 对同一来源哈希幂等返回既有 draft/版本，不重复写向量。

`index_rule_pages` 的核心写入必须相当于：

```python
citation = {
    "source_type": "rule",
    "source_document_id": source_document_id,
    "source_part_id": page.source_part_id,
    "rule_set_version_id": rule_set_version_id,
    "page_number": page.page_number,
    "start_offset": start_offset,
    "end_offset": end_offset,
}
```

管理员 API：

- `POST /api/rag/coc7/import-authoritative`：导入固定文件；
- `GET /api/rag/rule-set-versions/{id}/audit`：返回来源指纹、页状态统计、门槛和必要页内摘录；
- `POST /api/rag/rule-set-versions/{id}/audit/approve`：仅管理员可将没有 `needs_review` 的版本置为可发布；
- 已有 publish API 在事务内校验 gate 为 `ready`，成功后将 `runtime_eligible=TRUE`。

- [ ] **Step 4: 运行 Task 2 测试确认通过**

Run: `python -m pytest tests/server/test_authoritative_coc7.py tests/server/test_rag_router.py tests/server/test_rag_versioning.py -q`

Expected: PASS。

- [ ] **Step 5: 提交 Task 2**

```bash
git add src/server/rules/authoritative_coc7.py src/server/ai/rag.py src/server/rag_router.py tests/server/test_authoritative_coc7.py tests/server/test_rag_router.py tests/server/test_rag_versioning.py
git commit -m "feat: import and audit authoritative CoC7 rules"
```

## Task 3: 合格版本检索、中文词法召回与旧版隔离

**Files:**
- Modify: `src/server/ai/rag.py`
- Modify: `src/server/rag_router.py`
- Modify: `src/server/ai/ai_config.py`
- Modify: `src/server/rule_source_lifecycle.py`
- Modify: `tests/server/test_rag_search.py`
- Modify: `tests/server/test_rag_router.py`
- Modify: `tests/server/test_authoritative_coc7.py`

**Interfaces:**
- Consumes `runtime_eligible`、已发布 gate 与规则 source pages。
- Produces `_cjk_lexical_patterns(query) -> list[str]` 和 `RAGStore.search` 的规则安全过滤。
- Produces `retire_local_test_rule_versions(conn)`，只隔离 `metadata.local_test_only=true` 的旧规则和其绑定房间。

- [ ] **Step 1: 写入失败的检索/隔离测试**

```python
def test_explicit_legacy_rule_version_cannot_bypass_runtime_eligibility():
    store.search("幸运值如何回复", audience="admin", rule_set_version_id="legacy-v1")
    assert "runtime_eligible = TRUE" in cursor.main_sql


def test_chinese_rule_query_uses_character_lexical_candidates():
    store.search("孤注一掷失败会发生什么", source_types=["rule"])
    assert "%孤注%" in cursor.main_params
    assert "%一掷%" in cursor.main_params


def test_irrelevant_rule_result_is_not_returned_when_score_is_below_threshold():
    assert store.search("量子护盾", source_types=["rule"]) == []


def test_quarantine_local_test_version_marks_only_its_dependent_rooms(test_db):
    result = retire_local_test_rule_versions(test_db)
    assert result["retired_rooms"] == 1
    assert test_db.execute("SELECT rule_source_status FROM rooms WHERE room_id = 'legacy-room'").fetchone()["rule_source_status"] == "rule_source_retired"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/server/test_rag_search.py tests/server/test_authoritative_coc7.py -q`

Expected: FAIL，旧版仍可返回、中文词法候选不存在或低相关规则仍被返回。

- [ ] **Step 3: 实现统一资格过滤和中文混合检索**

所有 `document_chunks.source_type='rule'` 查询必须加统一 `EXISTS` 条件，连接 `rule_set_versions`、`rule_sets` 与 publication gate，要求：`status='published'`、`runtime_eligible=TRUE`、规则集已发布、gate 状态为 `ready`。将同一条件用于：房间绑定候选、场景绑定候选、默认基础规则、显式 `rule_set_version_id` 和 `frozen_rule_policy_sources`。

对中文查询：先删除常见疑问短语，再生成去重的 2–4 字连续片段；以 `content ILIKE` 片段匹配补充当前向量和全文检索分数。规则结果在外层筛除：只有词法证据达到最低比例，或向量分数达到规则阈值，才返回。非规则语料保持现有召回行为。

隔离函数必须在事务内将 `metadata.local_test_only=true` 的版本标记为不可运行，并将使用该版本的房间标记 `rule_source_retired`/`local_test_rule_version`；不得删除任何行。

- [ ] **Step 4: 运行 Task 3 测试确认通过**

Run: `python -m pytest tests/server/test_rag_search.py tests/server/test_rag_router.py tests/server/test_authoritative_coc7.py -q`

Expected: PASS。

- [ ] **Step 5: 提交 Task 3**

```bash
git add src/server/ai/rag.py src/server/rag_router.py src/server/ai/ai_config.py src/server/rule_source_lifecycle.py tests/server/test_rag_search.py tests/server/test_rag_router.py tests/server/test_authoritative_coc7.py
git commit -m "fix: restrict RAG to authoritative rule versions"
```

## Task 4: 旧房间阻断与 AI-KP 临时裁定

**Files:**
- Modify: `src/server/rule_source_lifecycle.py`
- Modify: `src/server/router_rooms.py`
- Modify: `src/server/player/auth.py`
- Modify: `src/server/host/router_host.py`
- Modify: `src/server/rag_router.py`
- Modify: `src/server/ai/ai_kp.py`
- Modify: `src/server/ai/rag_context.py`
- Create: `tests/server/test_room_rule_source_lifecycle.py`
- Modify: `tests/server/test_rooms.py`
- Modify: `tests/server/test_rag_context.py`

**Interfaces:**
- Consumes `ensure_room_rule_source_available(conn, room_id)` and `find_room_adjudication(conn, room_id, question)`.
- Produces `RuleSourceRetiredError` mapped to `409` with `{"code":"rule_source_retired","reason":"local_test_rule_version"}`.
- Produces `upsert_room_adjudication(conn, room_id, question, summary, minimal_state, rule_version_id)`.

- [ ] **Step 1: 写入失败的房间和裁定测试**

```python
def test_retired_room_cannot_be_opened_by_player_or_host(client, test_db):
    test_db.execute("UPDATE rooms SET rule_source_status = 'rule_source_retired', rule_source_reason = 'local_test_rule_version' WHERE room_id = 'room-1'")
    assert client.get("/api/rooms/room-1").status_code == 409
    assert client.get("/api/host/room-1/hud", headers=owner_headers).json()["detail"]["code"] == "rule_source_retired"


def test_no_rule_evidence_reuses_only_the_current_room_adjudication(test_db):
    upsert_room_adjudication(test_db, "room-a", "我能砸开门吗", "门锁被撬开", {"scene": "门厅"}, "")
    assert find_room_adjudication(test_db, "room-a", "我能砸开门吗")["summary"] == "门锁被撬开"
    assert find_room_adjudication(test_db, "room-b", "我能砸开门吗") is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/server/test_room_rule_source_lifecycle.py tests/server/test_rooms.py tests/server/test_rag_context.py -q`

Expected: FAIL，失效房间仍可读取或临时裁定 API 尚不存在。

- [ ] **Step 3: 实现阻断和临时裁定**

在房间公开读取、房主验证、玩家角色验证、RAG 房间授权和新房间创建路径调用同一个守卫。守卫只拦截 `rule_source_status='rule_source_retired'`；管理员详情、管理员删除和审计仍可读。创建房间时，如果已有 CoC7 基础规则集却没有合格发布版本，返回 `409 rule_source_unavailable`；有合格版本时写入 `room_rule_bindings`，将该房间固定到当前正式版本。

`ai_kp` 和 RAG context 仅在规则候选为空时读取当前房间匹配的临时裁定；生成的无依据剧情结果以规范化问题键、最小场景状态和摘要 upsert 到当前房间。向模型提供的内容不得含管理员身份、token、原始安全边界文本或未揭示秘密。玩家、房主的响应不出现“临时裁定”字样、规则页码或原文。

- [ ] **Step 4: 运行 Task 4 测试确认通过**

Run: `python -m pytest tests/server/test_room_rule_source_lifecycle.py tests/server/test_rooms.py tests/server/test_rag_context.py tests/server/test_rag_security.py -q`

Expected: PASS。

- [ ] **Step 5: 提交 Task 4**

```bash
git add src/server/rule_source_lifecycle.py src/server/router_rooms.py src/server/player/auth.py src/server/host/router_host.py src/server/rag_router.py src/server/ai/ai_kp.py src/server/ai/rag_context.py tests/server/test_room_rule_source_lifecycle.py tests/server/test_rooms.py tests/server/test_rag_context.py
git commit -m "feat: retire legacy rule rooms safely"
```

## Task 5: 管理员房间服务端分页

**Files:**
- Modify: `src/server/router_admin.py`
- Create: `tests/server/test_admin_room_pagination.py`
- Modify: `tests/server/test_admin_bulk_delete.py`

**Interfaces:**
- `GET /api/admin/rooms?page=<positive int>&page_size=<10|30|50>` 返回 `{items, page, page_size, total, total_pages}`。
- 无 `page` 与 `page_size` 参数时继续返回原有数组，以保护旧调用。

- [ ] **Step 1: 写入失败的分页测试**

```python
def test_admin_room_list_paginates_with_total_and_stable_order(client, test_db):
    _insert_rooms(test_db, 31)
    response = client.get("/api/admin/rooms?page=2&page_size=30", headers=admin_headers)
    assert response.json()["total"] == 31
    assert response.json()["page"] == 2
    assert len(response.json()["items"]) == 1


@pytest.mark.parametrize("query", ["?page=0&page_size=10", "?page=1&page_size=20"])
def test_admin_room_list_rejects_invalid_page_parameters(client, query):
    assert client.get(f"/api/admin/rooms{query}", headers=admin_headers).status_code == 422
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/server/test_admin_room_pagination.py -q`

Expected: FAIL，因为现有端点始终返回数组。

- [ ] **Step 3: 最小实现分页端点**

用参数对成对出现与 `page >= 1`、`page_size in {10,30,50}` 做验证。执行单独 `COUNT(*)`，按 `created_at DESC, room_id DESC` 获取稳定页，计算 `total_pages=max(1, ceil(total/page_size))`。每个 item 包含已有展示字段与 `rule_source_status`、`rule_source_reason`，不暴露 owner token。保持无参数数组兼容。

- [ ] **Step 4: 运行 Task 5 测试确认通过**

Run: `python -m pytest tests/server/test_admin_room_pagination.py tests/server/test_admin_bulk_delete.py -q`

Expected: PASS。

- [ ] **Step 5: 提交 Task 5**

```bash
git add src/server/router_admin.py tests/server/test_admin_room_pagination.py tests/server/test_admin_bulk_delete.py
git commit -m "feat: paginate admin room list"
```

## Task 6: 房间分页、当前页全选与前端回归

**Files:**
- Modify: `src/client/src/pages/AdminDashboard.tsx`
- Modify: `src/client/src/styles.css`
- Create: `src/client/src/pages/AdminDashboard.test.tsx`

**Interfaces:**
- Produces `normalizeRoomPageResponse`、`nextRoomPageAfterDeletion`、`toggleCurrentPageSelection`（纯函数，可直接 Vitest）。
- `RoomsPanel` 始终以分页请求加载；全选只使用 `pageItems.map(room => room.room_id)`。

- [ ] **Step 1: 写入失败的 UI 行为测试**

```tsx
test('current-page select all never includes another page', () => {
  const selected = toggleCurrentPageSelection([], ['room-11', 'room-12']);
  expect(selected).toEqual(['room-11', 'room-12']);
  expect(toggleCurrentPageSelection(selected, ['room-11', 'room-12'])).toEqual([]);
});

test('deleting the only item on the last page moves to the preceding page', () => {
  expect(nextRoomPageAfterDeletion({ page: 3, pageSize: 10, total: 21, deleted: 1 })).toBe(2);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd src/client && npm run test -- AdminDashboard.test.tsx`

Expected: FAIL，因为帮助函数尚不存在。

- [ ] **Step 3: 实现最小分页 UI**

替换 `rooms` 全量状态为 `{items, total, page, pageSize, totalPages}`。默认 10 条，`select` 只提供 10/30/50；上一页/下一页有明确禁用状态和当前范围文本。切页和改 pageSize 时调用 `setSelectedIds([])`；“全选本页”仅切换当前 `items`；复选框点击仍 `stopPropagation`，卡片点击仍只查看详情。

批量删除后重新请求当前页；若 `items` 为空而 `page > 1`，用 `nextRoomPageAfterDeletion` 请求上一有效页。保留现有 `BatchDeleteToolbar` 双重确认、逐项反馈和只移除 `deleted_ids` 的行为。为 `rule_source_retired` 房间显示“规则源已失效，无法打开”而不将其当作普通游戏状态。

- [ ] **Step 4: 运行 Task 6 测试和构建确认通过**

Run: `cd src/client && npm run test -- AdminDashboard.test.tsx`

Expected: PASS。

Run: `cd src/client && npm run build`

Expected: PASS。

- [ ] **Step 5: 提交 Task 6**

```bash
git add src/client/src/pages/AdminDashboard.tsx src/client/src/pages/AdminDashboard.test.tsx src/client/src/styles.css
git commit -m "feat: paginate room administration"
```

## Task 7: 集成验证、管理员导入与浏览器验收

**Files:**
- Modify: `docs/60-验收与测试报告/2026-08-13-authoritative-coc7-rag-room-admin-validation.md`

**Interfaces:**
- Consumes已发布代码、管理员授权、当前本地数据库和固定 380 页源文件。
- Produces可复现的测试记录，不物理删除任何旧测试资料。

- [ ] **Step 1: 运行完整定向后端验证**

Run:

```bash
python -m pytest tests/server/test_authoritative_coc7.py tests/server/test_rag.py tests/server/test_rag_search.py tests/server/test_rag_router.py tests/server/test_rag_versioning.py tests/server/test_rag_security.py tests/server/test_room_rule_source_lifecycle.py tests/server/test_rooms.py tests/server/test_admin_room_pagination.py tests/server/test_admin_bulk_delete.py -q
```

Expected: PASS。若联合运行超时，记录逐文件通过结果，并保留超时的命令与时间；不得宣称全套通过。

- [ ] **Step 2: 运行前端验证**

Run:

```bash
cd src/client && npm run test
cd src/client && npm run build
```

Expected: PASS；若既有无关失败，报告为既有失败并附单文件本次测试证据。

- [ ] **Step 3: 在本地管理员会话进行真实导入与隔离**

以管理员登录调用：导入 380 页正式源、检查 audit 返回 380 页和固定 SHA-256、只有 gate `ready` 时审核并发布；随后显式调用隔离本地测试规则的确认端点。不得物理 delete。

- [ ] **Step 4: 浏览器验收**

以管理员身份在 `/rag-test` 与 `/admin` 验证：

1. 规则审计显示正式来源、380 页统计及真实页码；
2. 自然中文问法命中相关页，虚构“量子护盾”不显示无关规则；
3. 隔离旧版后受影响旧房间显示稳定失效状态，管理员仍可删除；
4. 房间列表在 10/30/50 条之间切换；当前页全选、确认删除、部分失败提示、删空末页回退均无控制台错误；
5. 窄屏下分页和确认按钮可操作。

- [ ] **Step 5: 写入验证记录并提交**

记录每项命令、通过/失败状态、实际导入版本 ID、浏览器验收证据和未执行原因。不得记录管理员 token、账号身份或原始敏感上下文。

```bash
git add docs/60-验收与测试报告/2026-08-13-authoritative-coc7-rag-room-admin-validation.md
git commit -m "test: record authoritative CoC7 validation"
```

## 计划自查

- 来源完整性、逐页引用、发布门槛：Tasks 1–2。
- 旧资料隔离、中文召回与拒绝无关规则：Task 3。
- 旧房间失效、AI-KP 局部临时裁定与访问隔离：Task 4。
- 房间 API 分页与前端当前页删除：Tasks 5–6。
- 实际来源导入、后端/前端/浏览器证据：Task 7。
- 不包含物理清理旧资料或为其他三个管理页新增分页，符合已确认非目标。
