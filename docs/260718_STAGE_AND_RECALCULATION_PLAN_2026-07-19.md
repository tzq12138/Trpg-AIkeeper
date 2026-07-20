# 公共舞台控制与原骰复算实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 补齐 260718 协议中公共舞台的安全演出控制，以及规则参数修正时复用原骰的可审计重算。

**Architecture:** 舞台控制使用房主鉴权 REST 命令驱动已持久化的 `HostStore` 演出步骤。控制命令只改变演出游标与安全释放门，不调用 AI、规则引擎或 `StateService`。原骰重算从已保存 `ResolutionBundle` 的规则解释读取已验证 `roll_trace`，创建新的审计记录与补偿事务，不删除既有 action、事件或结果包。

**Tech Stack:** FastAPI、PostgreSQL、React/Vite、pytest、Vitest。

## 约束

- 房主前端不得直接修改世界状态、骰子、成功等级、生命值、理智、物品、线索或真相。
- 公共舞台 DTO 不得携带玩家私密投影、隐藏难度、完整规则参数或 Host 审核内容。
- 任何重算必须复用已记录骰点，不得重新调用随机源。
- 重算与补偿必须保留原 action、原 bundle 和不可删除审计记录。
- 不提交、清理或重置当前已有的无关工作树变更。

---

## 实施状态（2026-07-19）

- **Task 1 已完成**：持久化演出游标、暂停状态、开始/暂停/下一步/跳过视觉步骤与安全重放端点均已实现；`skip-visual` 仅跳过连续 `scene_transition`，并按每个已保存 `step_id` 逐项释放投影；公共投影从已发布 `stage_projection` 单独构建，绝不读取 Host 交易载荷。
- **Task 2 已完成**：Host Console 提供开始、暂停、下一步、“跳过视觉步骤”与“重放公开步骤”；公共舞台只消费白名单后的公开叙事。
- **Task 3 已完成**：仅支持已签名 CoC7 技能检定的难度重算，拒绝缺失/篡改回执和客户端骰点；重算只写审计补偿事务，不自动改写世界状态。
- **Task 4 自动化部分已完成**：最新关联后端回归 `100 passed`，前端全量 Vitest `126 passed`，构建与 `git diff --check` 通过；真实浏览器、多人与真实供应商验收仍未执行。

---

### Task 1: 舞台演出控制服务与房主 API

**Files:**
- Modify: `src/server/host/host_store.py`
- Modify: `src/server/host/router_host.py`
- Modify: `tests/server/test_host.py`

**Interfaces:**
- `HostStore.presentation_paused: bool` 独立于现有 `is_paused`。
- `HostStore.advance_presentation()` 返回已推进的 `TransactionStep | None`，仅移动 `current_step_index`。
- `POST /api/host/{room_id}/presentation/play|pause|next` 返回安全演出状态；`next` 只在未暂停时推进一个持久化步骤。
- `GET /api/host/{room_id}/presentation` 返回 `transactionId`、`currentStepIndex`、`totalSteps`、`paused` 与已播放步骤的公共摘要；不返回私密 payload。

- [ ] **Step 1: 写失败测试**

```python
def test_owner_can_advance_one_persisted_presentation_step_without_world_mutation(client, test_db):
    room, store = make_room_with_reveal_transaction(client, test_db)

    response = client.post(
        f"/api/host/{room['room_id']}/presentation/next",
        headers={"X-Owner-Token": room["owner_token"]},
    )

    assert response.status_code == 200
    assert response.json()["currentStepIndex"] == 1
    assert store.current_step_index == 1
    assert_world_state_unchanged(test_db, room["room_id"])
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/server/test_host.py -q -k presentation_next`

Expected: 失败，因为 presentation 路由和演出状态尚不存在。

- [ ] **Step 3: 最小服务端实现**

```python
@router.post("/{room_id}/presentation/next")
async def advance_presentation(request: Request, room_id: str):
    _verify_owner(request, room_id)
    store = get_host_store(room_id, request.app.state.db)
    if store.presentation_paused:
        raise HTTPException(409, "Presentation is paused")
    step = store.advance_presentation()
    store.save_state(request.app.state.db)
    return presentation_snapshot(store, step)
```

实现必须通过已存在的 `step_id` 校验释放对应延迟投影；不得调用 `ResolutionPipeline`、AI、`RuleExecutor` 或 `StateService`。

- [ ] **Step 4: 验证通过与回归**

Run: `python -m pytest tests/server/test_host.py -q`

Expected: 全部通过，新增覆盖鉴权、暂停拒绝、重连恢复、单步推进与无状态改写。

### Task 2: 房主控制台的安全演出面板

**Files:**
- Modify: `src/client/src/pages/HostConsole.tsx`
- Modify: `src/client/tests/host-stage.test.ts`

**Interfaces:**
- `HostPresentationControls` 只接收 `transactionId`、`currentStepIndex`、`totalSteps`、`paused` 和回调。
- 控制台可调用 `play`、`pause`、`next` 和只读 `replay`；公共舞台仍不显示控制、精确资源或导演内容。

- [ ] **Step 1: 写失败测试**

```tsx
test('renders presentation controls without direct rule or state mutation actions', async () => {
  const { HostPresentationControls } = await import('../src/pages/HostConsole');
  const html = renderToStaticMarkup(<HostPresentationControls state={state} onCommand={() => {}} />);

  expect(html).toContain('演出控制');
  expect(html).toContain('下一步');
  expect(html).not.toContain('直接裁决');
  expect(html).not.toContain('修改 HP');
});
```

- [ ] **Step 2: 验证测试先失败**

Run: `cd src/client && npm run test -- --run tests/host-stage.test.ts`

Expected: 失败，因为组件尚未导出。

- [ ] **Step 3: 最小前端实现**

```tsx
export function HostPresentationControls({ state, onCommand }: Props) {
  return <section aria-label="演出控制">...</section>;
}
```

实现通过房主认证请求调用 Task 1 的端点；重放仅重新显示服务器返回的已播放公共步骤，不发送新的 ACK。

- [ ] **Step 4: 验证通过与构建**

Run: `cd src/client && npm run test -- --run tests/host-stage.test.ts && npm run build`

Expected: 测试和构建通过。

### Task 3: 原骰重算与补偿审计

**Files:**
- Modify: `src/server/engine/compensation_service.py`
- Modify: `src/server/host/router_action_reviews.py`
- Modify: `src/server/models.py`
- Modify: `tests/server/test_action_reviews_v2.py`

**Interfaces:**
- `POST /api/host/{room_id}/action-reviews/{review_request_id}/recalculate` 接受仅规则参数修正的 allowlist，返回 `compensation_transaction_id`。
- 服务端从原 `ResolutionBundle.rule_explanation.verification_receipt` / `roll_trace` 读取骰点，重算不接受客户端骰点。
- 结果写入 `compensation_transactions` 与 `action_review_requests.resolution`，记录原 action、原 roll trace、修正参数和新状态版本。

- [ ] **Step 1: 写失败测试**

```python
def test_host_recalculation_reuses_saved_roll_trace_and_creates_a_compensation_transaction(client, test_db):
    room, review = make_review_with_completed_skill_check(client, test_db, roll=42)

    response = client.post(
        f"/api/host/{room['room_id']}/action-reviews/{review['id']}/recalculate",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"difficulty": "hard", "reason": "难度参数录入错误"},
    )

    assert response.status_code == 200
    assert_saved_roll_trace(test_db, response.json()["compensation_transaction_id"], [42])
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/server/test_action_reviews_v2.py -q -k recalculation`

Expected: 失败，因为路由与重算服务尚不存在。

- [ ] **Step 3: 最小后端实现**

```python
def recalculate_action_review(app_state, conn, review, parameter_patch, reason):
    original = load_resolution_bundle(conn, review["action_id"])
    trace = verified_roll_trace(original)
    result = execute_with_saved_roll_trace(original, parameter_patch, trace)
    return persist_compensation_transaction(conn, review, result, reason, trace)
```

参数只允许已实现 CoC7 机制的难度与安全规则修正；缺少可验证 trace、非 allowlist 字段或试图提供骰点时返回 422，不写入状态。

- [ ] **Step 4: 验证通过与回归**

Run: `python -m pytest tests/server/test_action_reviews_v2.py tests/server/test_coc7_core_rules.py tests/server/test_action_lifecycle_v2.py -q`

Expected: 全部通过，测试证明原骰复用、非法参数拒绝、历史保留与补偿原子性。

### Task 4: 验收记录

**Files:**
- Modify: `docs/260718_COMPLETION_AUDIT_2026-07-19.md`

- [ ] **Step 1: 记录实际命令与结果**

记录每个新增端点、前端控件、失败路径和定向测试的实际输出；浏览器证据与自动化证据分开标识。

- [ ] **Step 2: 运行格式检查**

Run: `git diff --check`

Expected: exit code 0；既有 LF→CRLF 警告单独说明，不作为补丁错误。
