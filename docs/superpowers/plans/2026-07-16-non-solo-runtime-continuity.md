# 普通剧本运行时连续性与自然结局实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让已验证的普通剧本行动在叙事供应商传输失败时仍可连续结算，并只在已提取、可审计的结局条件满足时自然完成房间。

**Architecture:** 运行时将已通过 DirectorPlan 和规则校验的状态结果与叙事演绎分离：仅在超时或调用异常时渲染本地事实叙事，模型输出的格式或事实违规仍封闭到异常队列。导入器把结局从描述性条目升级为带引用的声明式条件；结算管线在状态写入后以确定性求值器评估它们，再发出完成事件和结局叙事。

**Tech Stack:** FastAPI、PostgreSQL JSON、Pydantic、pytest、React/Vite 浏览器验收。

## Global Constraints

- 仅处理非《向火独行》普通剧本；不将编号条目或隐藏结局投影给玩家。
- 传输失败可以使用 `build_verified_narration`；无 citation、格式错误、事实冲突的模型输出必须保持 `awaiting_host_exception`。
- 结局只接受导入时提取并带 citation 的显式条件；没有条件的旧版本不可自动完成。
- 不触碰现有未提交的无关修改；本轮不提交、不推送。

---

### Task 1: 普通剧本的已验证叙事降级

**Files:**
- Modify: `src/server/engine/resolution_pipeline.py:1222-1310`
- Modify: `tests/server/test_narrator_runtime.py`

**Interfaces:**
- Consumes: `build_narrator_context(...)`、已验证的 `DirectorPlan`、`ResolutionResult`。
- Produces: 成功状态的 `resolution.metadata["narration"]`，其中 `provider_source="local_fallback"` 和 `rejected_provider_reason` 仅对应传输失败。

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_non_solo_timeout_uses_verified_local_narration(test_db, monkeypatch):
    # Arrange a V2 action with a valid DirectorPlan and a scene fact.
    # Force asyncio.wait_for to raise TimeoutError.
    result = await pipeline.resolve_action("narrator-action")
    assert result["status"] == "completed"
    assert result["result"]["metadata"]["narration"]["provider_source"] == "local_fallback"
    assert result["result"]["metadata"]["narration"]["rejected_provider_reason"] == "narrator_timeout"
```

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest tests/server/test_narrator_runtime.py::test_non_solo_timeout_uses_verified_local_narration -q`

Expected: FAIL，因为当前普通剧本返回 `awaiting_host_exception`。

- [ ] **Step 3: 写最小实现**

```python
except TimeoutError:
    if context is not None and self._has_verified_director_plan(action, room):
        self._apply_verified_narration_fallback(
            context, action, resolution, rejected_provider_reason="narrator_timeout"
        )
        return None
    return "narrator_timeout"
```

`_has_verified_director_plan` 只接受 `state_patch_authority="advisory_only"`、匹配 `context_version`、无被拒权限的计划；不接受模型输出验证失败。

- [ ] **Step 4: 运行绿灯测试**

Run: `python -m pytest tests/server/test_narrator_runtime.py -q`

Expected: PASS，且原有无效 narrator 输出测试仍保持异常队列。

### Task 2: 通用场景语义进度的导入与执行

**Files:**
- Modify: `src/server/ai/ai_kp.py:280-305`
- Modify: `src/server/scenario/content_projection.py:9-270`
- Modify: `src/server/ai/director.py:216-430`
- Modify: `src/server/engine/resolution_pipeline.py:620-710`
- Modify: `tests/server/test_content_package.py`
- Modify: `tests/server/test_director_runtime.py`
- Modify: `tests/server/test_narrator_runtime.py`

**Interfaces:**
- Consumes: `knowledge_graph.scenes`、带 citation 的 `knowledge_graph.branches` 和房间权威的 `room_scene_state`。
- Produces: Director 专用的当前场景可达边，以及只在已校验场景边上更新的 `room_scene_state.current_scene`、`visited_scenes` 与 `s2c_scene_sync`。
- Boundary: 条件只接受已持久化的场景或已发现线索；未带 citation、来源场景不匹配、目标不可达或条件未满足的推进不得改状态。

- [ ] **Step 1: 写失败测试**

```python
def test_content_projection_keeps_cited_scene_branch():
    graph = {
        "scenes": [{"scene_id": "study", "name": "书房"}, {"scene_id": "harbor", "name": "码头"}],
        "branches": [{
            "branch_id": "study_to_harbor",
            "from_scene_id": "study",
            "to_scene_id": "harbor",
            "citation": {"page_number": 8},
        }],
    }
    ContentProjectionService(test_db).rebuild(scenario_version_id, graph, requested_by="test-admin")
    edge = test_db.execute("SELECT * FROM content_item_edges WHERE scenario_version_id = %s", (scenario_version_id,)).fetchone()
    assert edge["edge_type"] == "transitions_to"
```

```python
def test_director_validates_only_current_cited_generic_scene_edge(test_db):
    plan = DirectorPlanDTO(
        semantic_progression={"targetNodeId": "harbor", "citation": {"page_number": 8}},
        ...,
    )
    result = apply_director_plan(test_db, character, plan, context)
    assert result["semantic_progression"]["validated"] is True
```

```python
@pytest.mark.asyncio
async def test_validated_generic_scene_progression_updates_authoritative_scene_state(test_db):
    result = await pipeline.resolve_action("generic-scene-action")
    assert result["status"] == "completed"
    scene = test_db.execute("SELECT current_scene, visited_scenes FROM room_scene_state WHERE room_id = %s", (room_id,)).fetchone()
    assert scene["current_scene"] == "harbor"
    assert "harbor" in scene["visited_scenes"]
```

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest tests/server/test_content_package.py tests/server/test_director_runtime.py tests/server/test_narrator_runtime.py -q`

Expected: FAIL，因为普通剧本没有结构化分支、Director 不暴露或验证普通场景边，结算也不会更新通用场景状态。

- [ ] **Step 3: 写最小实现**

扩展结构化导入提示和规范化器以保留 `branches`；由 `ContentProjectionService` 将来源、目标、条件和 citation 归一为 `transitions_to` 边。`_compact_runtime_package` 仅向 Director 提供当前场景发出的边，`_validate_semantic_progression` 同时校验来源、目标、citation 和白名单条件。通过后，结算管线使用已有 `StateService.apply_change(..., SceneChange(...))` 在同一状态服务内写入场景、访问记录和同步事件；不为普通剧本复制 Solo 运行时。

- [ ] **Step 4: 运行绿灯测试**

Run: `python -m pytest tests/server/test_content_package.py tests/server/test_director_runtime.py tests/server/test_narrator_runtime.py -q`

Expected: PASS，且不可达、无 citation 与不满足条件的普通推进仍不改 `room_scene_state`。

### Task 3: 声明式结局条件的导入契约

**Files:**
- Modify: `src/server/ai/ai_kp.py:280-305`
- Modify: `src/server/ai/director.py:216-269`
- Modify: `src/server/scenario/module_compiler.py:350-406`
- Modify: `tests/server/test_content_package.py`
- Modify: `tests/server/test_director_runtime.py`

**Interfaces:**
- Consumes: `knowledge_graph.endings[*]` 的来源 citation 与 `completion_conditions`。
- Produces: 仅给 Director 的 `runtime_package["ending_conditions"]`；每个条件使用 `all_clues`、`any_clues`、`entered_scenes`、`event_types` 或 `room_status` 中的声明式键。

- [ ] **Step 1: 写失败测试**

```python
def test_runtime_package_preserves_cited_completion_conditions():
    graph = {
        "endings": [{
            "ending_id": "escape",
            "name": "逃离",
            "citation": {"page_number": 8},
            "completion_conditions": {"entered_scenes": ["harbor"]},
        }]
    }
    package = _build_runtime_package(..., graph=graph, ...)
    assert package["ending_conditions"][0]["completion_conditions"] == {"entered_scenes": ["harbor"]}
```

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest tests/server/test_content_package.py::test_runtime_package_preserves_cited_completion_conditions -q`

Expected: FAIL，因为当前导入提示和运行包没有可执行条件字段。

- [ ] **Step 3: 写最小实现**

扩展结构化提示、规范化器和运行包编译，拒绝没有 citation 或包含未知键的条件；`_compact_runtime_package` 只将该字段交给 Director，不进入 Narrator 或玩家 DTO。

- [ ] **Step 4: 运行绿灯测试**

Run: `python -m pytest tests/server/test_content_package.py tests/server/test_director_runtime.py -q`

Expected: PASS，且玩家投影中没有结局字段。

### Task 4: 确定性普通剧本结局求值与完成事件

**Files:**
- Create: `src/server/engine/ending_conditions.py`
- Modify: `src/server/engine/resolution_pipeline.py:525-670`
- Modify: `tests/server/test_narrator_runtime.py`
- Create: `tests/server/test_ending_conditions.py`

**Interfaces:**
- Consumes: `runtime_package["ending_conditions"]`、已持久化房间/事件/场景/线索状态。
- Produces: `EndingDecision(ending_id, ending_type, citation)` 或 `None`；只有决策非空时写入 `rooms.status='completed'` 与 `s2c_campaign_ended`。

- [ ] **Step 1: 写失败测试**

```python
def test_evaluate_ending_requires_all_declared_facts(test_db):
    decision = evaluate_ending_conditions(
        test_db,
        room_id="room-1",
        ending_conditions=[{
            "ending_id": "escape",
            "citation": {"page_number": 8},
            "completion_conditions": {"event_types": ["s2c_clue_revealed"], "room_status": "active"},
        }],
    )
    assert decision is None
```

```python
@pytest.mark.asyncio
async def test_completed_action_marks_room_completed_when_cited_ending_matches(test_db):
    # Seed a cited matching ending and the required event.
    result = await pipeline.resolve_action("narrator-action")
    assert result["status"] == "completed"
    assert test_db.execute("SELECT status FROM rooms WHERE room_id = %s", (room_id,)).fetchone()["status"] == "completed"
```

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest tests/server/test_ending_conditions.py -q`

Expected: FAIL，因为求值器尚不存在，普通房间不会自动完成。

- [ ] **Step 3: 写最小实现**

`evaluate_ending_conditions` 只识别白名单键，使用数据库事实逐项 AND 验证；缺 citation、未知条件、空条件或多结局同时命中均返回 `None`。管线在状态变更和 narration 后调用它，在单一决定命中时更新房间、向所有玩家投影完成事件，并给已验证叙事设置 `adventure_ended=True`。

- [ ] **Step 4: 运行绿灯测试**

Run: `python -m pytest tests/server/test_ending_conditions.py tests/server/test_narrator_runtime.py -q`

Expected: PASS，未满足或歧义结局永不改变房间状态。

### Task 5: 重新导入并浏览器验收两份普通剧本

**Files:**
- Modify: `scripts/run_golden_module_suite.py`
- Modify: `docs/loop_runs/2026-07-16-two-nonyhdx-playthrough-progress.md`

**Interfaces:**
- Consumes: 已启用的图文供应商、导入后的 `completion_conditions`。
- Produces: 两个隔离房间的真实 `completed` 状态、玩家与 AI KP 操作轨迹、citation 和问题记录。

- [ ] **Step 1: 写失败验收断言**

```python
assert all(result["room_status"] == "completed" for result in selected_non_yhdx_results)
assert all(result["completion_source"] == "verified_runtime_ending" for result in selected_non_yhdx_results)
```

- [ ] **Step 2: 运行红灯验收**

Run: `python scripts/run_golden_module_suite.py --root "G:\\hermes-agent-workplace\\D&D\\CodeX-aikeeper\\data\\test_assets\\六类黄金样本"`

Expected: FAIL 或报告旧的手动归档完成路径，不能作为自然通关证据。

- [ ] **Step 3: 使用启用供应商重新导入两个普通剧本**

在隔离库中导入《猩红文档》和《常暗之厢》，仅当运行包门禁包含 citation 完整的 `completion_conditions` 时开房。

- [ ] **Step 4: 浏览器自然语言通关**

每个剧本使用独立 Host/Player：入房、选预设、开局、至少一条调查/移动/规则行动、AI/本地降级叙事、满足结局条件、验证房间状态为 `completed`。不点击 Host 结束，不调用归档结束接口。

- [ ] **Step 5: 运行最终验证**

Run: `python -m pytest tests/server -q; cd src/client; npm run test; npm run build; git diff --check`

Expected: 全部通过；报告明确区分已通过、未通过和环境性限制。
