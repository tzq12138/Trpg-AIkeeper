# 全局线索触发条件统一 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让所有带 `reveal_conditions` 的运行时剧本根据已确认的玩家行动稳定结算线索，同时不将未揭示线索内容传给模型或玩家。

**Architecture:** 新增纯函数式运行时条件选择器，读取运行时包、当前场景、玩家行动与已知线索，返回至多一条安全的候选线索及未知条件诊断。`ResolutionPipeline` 保持唯一持久化入口并以现有行动事务、UUID 和事件投影保证幂等；导演上下文不再携带原始 `clue_dependencies`。

**Tech Stack:** Python 3、FastAPI、PostgreSQL/测试数据库适配器、pytest。

**Spec:** `docs/superpowers/specs/2026-08-30-global-reveal-conditions-design.md`

## Global Constraints

- 不改写现有剧本的 `reveal_conditions` 数组，不新增数据库迁移、公开 API 或前端设置项。
- 数组中的条件为 OR；`prerequisite_fact_refs` 为 AND。
- 仅后端确定性规则授权；AI 的超时、遗漏或不合规结果不得阻断合格线索。
- 每个已确认行动最多持久化一条线索；同批候选中 `importance == "core"` 优先，其后按剧本声明顺序。
- 新线索继续是发现者私有；不得自动共享给队伍。
- 未揭示线索的名称、正文、`private_version`、前置条件细节和原始安全边界文本不得进入导演上下文、玩家事件或普通日志。
- 未知或无法解析的条件必须拒绝触发并写入最小管理员诊断；不得猜测或放宽匹配。
- 不自动升级、删除或修改既有房间；真实验收使用最新生成剧本创建的新房间。

---

## 文件结构

- 创建：`src/server/engine/runtime_reveal_conditions.py` — 纯运行时线索条件解析、行动证据、候选排序与最小拒绝诊断。
- 修改：`src/server/engine/resolution_pipeline.py` — 将现有“玩家提到线索名”持久化改为调用选择器、查询已知线索并写入安全玩家文本。
- 修改：`src/server/ai/director.py` — 从紧凑导演包中移除原始 `clue_dependencies`，保留兼容的空列表字段。
- 创建：`tests/server/test_runtime_reveal_conditions.py` — 纯规则、条件类型扫描和边界安全测试。
- 修改：`tests/server/test_progression_recovery.py` — 覆盖真实持久化、前置线索、失败保留、幂等和私有投影。
- 修改：`tests/server/test_director_runtime.py` — 覆盖当前场景原始线索数据也不会泄露给导演上下文。

## 公开接口

`src/server/engine/runtime_reveal_conditions.py` 将定义：

```python
SUPPORTED_REVEAL_CONDITION_KINDS = frozenset({
    "inspect", "research", "ask_npc", "ask", "talk",
})

@dataclass(frozen=True)
class RuntimeClueCandidate:
    canonical_id: str
    name: str
    player_text: str
    importance: str
    declaration_index: int

@dataclass(frozen=True)
class RuntimeClueSelection:
    candidate: RuntimeClueCandidate | None
    rejected_condition_kinds: tuple[str, ...]

def select_runtime_clue(
    runtime_package: Mapping[str, Any],
    current_scene_id: str,
    intent_type: str,
    declared_intent: str,
    known_canonical_ids: Collection[str],
    *,
    allow_failure_preservation: bool = False,
) -> RuntimeClueSelection: ...
```

`ResolutionPipeline._persist_named_runtime_clues(...)` 保留现有调用点，新增关键字参数 `allow_failure_preservation: bool = False`，并继续返回既有 `list[dict[str, Any]]` 事件发布结构。

### Task 1: 建立纯运行时条件选择器

**Files:**

- Create: `tests/server/test_runtime_reveal_conditions.py`
- Create: `src/server/engine/runtime_reveal_conditions.py`

**Interfaces:**

- Consumes: 已编译运行时包中的 `semantic_scenes`、`npc_states`、`character_and_items.items` 与 `clue_dependencies`。
- Produces: `select_runtime_clue(...) -> RuntimeClueSelection`，供 `ResolutionPipeline` 调用；不执行数据库写入。

- [ ] **Step 1: 写出失败的纯规则测试**

```python
def test_select_runtime_clue_requires_scene_action_and_all_prerequisites():
    selection = select_runtime_clue(
        _runtime_package_with_watchmaker(),
        "night-market",
        "dialogue",
        "我向钟师傅追问寄存牌上的刻痕。",
        {"brass-token"},
    )
    assert selection.candidate is not None
    assert selection.candidate.canonical_id == "token-scratch"
    assert selection.candidate.player_text == "修复的刻痕写着安全停机顺序。"


def test_select_runtime_clue_rejects_unknown_kind_and_does_not_fall_back():
    selection = select_runtime_clue(
        _runtime_package_with_unknown_condition(),
        "study",
        "dialogue",
        "我调查书桌。",
        set(),
    )
    assert selection.candidate is None
    assert selection.rejected_condition_kinds == ("unsupported_kind",)
```

同时覆盖：条件数组 OR、`inspect`/`research` 行为词、NPC 的 `name`/`public_name` 别名、未满足前置线索、未提及 NPC、`item_id` 找不到公开物件、`core` 优先、稳定声明顺序，以及从所有 `data/golden_modules/**/module.json` 收集到的条件类型均属于 `SUPPORTED_REVEAL_CONDITION_KINDS`。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/server/test_runtime_reveal_conditions.py -q`

Expected: FAIL，原因是 `runtime_reveal_conditions` 模块或 `select_runtime_clue` 尚不存在。

- [ ] **Step 3: 实现最小、纯函数的选择器**

```python
def select_runtime_clue(..., allow_failure_preservation: bool = False) -> RuntimeClueSelection:
    current_scene = _scene_context(runtime_package, current_scene_id)
    known = {str(value) for value in known_canonical_ids if str(value)}
    eligible = []
    rejected = []
    for index, dependency in enumerate(_dict_items(runtime_package.get("clue_dependencies"))):
        if not _has_canonical_id(dependency) or dependency["clue_id"] in known:
            continue
        if not _prerequisites_met(dependency, known):
            continue
        if allow_failure_preservation and not _preserves_core(dependency):
            continue
        matched, rejected_kind = _any_condition_matches(dependency, current_scene, intent_type, declared_intent)
        if rejected_kind:
            rejected.append(rejected_kind)
        if matched:
            eligible.append(_candidate_from_dependency(dependency, index))
    return RuntimeClueSelection(_rank(eligible), tuple(dict.fromkeys(rejected)))
```

实现细节：

- 仅接受 `inspect`、`research`、`ask_npc`、`ask`、`talk`；未知条件返回 `unsupported_kind`，不匹配。
- `inspect` 与 `research` 只识别固定中文/英文行为词；`ask_npc`、`ask`、`talk` 同时要求对话类行动、固定交谈词和当前场景 NPC 的 `name` 或 `public_name`。NPC 必须由当前 `semantic_scenes` 的 `npcs_present` 指向；未在场的 NPC 不可触发。
- 条件的 `scene_id` 必须等于当前稳定场景 ID；未给 `scene_id` 时才使用线索 `location` 与当前场景公开名称的兼容匹配。
- `item_id` 必须能从 `character_and_items.items` 解析到公开 `name`、`title` 或 `public_name`，且行动明确提到该别名。
- 候选文本只使用 `public_version`；缺失时降级到线索 `name`，绝不使用 `description` 或 `private_version`。
- 排序键为 `(importance != "core", declaration_index)`，使所有线索可被处理但核心线索优先。
- `allow_failure_preservation=True` 时只允许 `failure_outcome.preserve_core is True` 的候选；通常成功行动不受该限制。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/server/test_runtime_reveal_conditions.py -q`

Expected: PASS，且条件类型扫描覆盖两个已收录黄金模块。

- [ ] **Step 5: 提交本任务**

```bash
git add src/server/engine/runtime_reveal_conditions.py tests/server/test_runtime_reveal_conditions.py
git commit -m "feat: add runtime clue condition selector"
```

### Task 2: 用选择器替换线索名称匹配并保留幂等性

**Files:**

- Modify: `tests/server/test_progression_recovery.py:553-607`
- Modify: `src/server/engine/resolution_pipeline.py:1517-1586, 2220-2236, 4838-4979`

**Interfaces:**

- Consumes: Task 1 的 `select_runtime_clue` 与 `RuntimeClueCandidate`。
- Produces: 对每个行动至多一个 `runtime:<canonical_id>` 私有 clue、一个既有 `s2c_clue_discovered` 事件，并向现有 `runtime_clue_discoveries` 元数据追加安全记录。

- [ ] **Step 1: 写出失败的持久化回归测试**

```python
@pytest.mark.asyncio
async def test_runtime_condition_discovers_public_clue_without_player_knowing_its_name(test_db, monkeypatch):
    pipeline = _pipeline_at_scene(test_db, monkeypatch, "lost-property-counter")
    discovered = await pipeline._persist_named_runtime_clues(
        _action("inspect-counter", "room", "character"),
        PlayerIntent(
            action_id="inspect-counter",
            intent_type="dialogue",
            declared_intent="我仔细检查柜台上的寄存牌和取件簿。",
        ),
    )
    clue = test_db.execute("SELECT text, source, is_private FROM clues WHERE room_id = 'room'").fetchone()
    assert [item["canonicalId"] for item in discovered] == ["brass-token"]
    assert clue["source"] == "runtime:brass-token"
    assert clue["is_private"] is True
    assert "公开线索文本" in clue["text"]
    assert "私密线索文本" not in clue["text"]
```

再添加：缺少 `brass-token` 时不发现 `token-scratch`；插入拥有者或已分享的 `runtime:brass-token` 后，对“钟师傅”的正常追问发现 `token-scratch`；同一行动/同一候选重复调用不重复写入；失败行动只在 `preserve_core` 为真且 `allow_failure_preservation=True` 时结算；同场景多候选一次只写入排序后的第一条。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/server/test_progression_recovery.py -q`

Expected: FAIL，旧实现要求行动文本包含尚未揭示的线索名称，并使用 `description` 写入线索。

- [ ] **Step 3: 最小化改造 `ResolutionPipeline`**

```python
selection = select_runtime_clue(
    runtime_package,
    current_scene_id,
    intent.intent_type,
    intent.declared_intent,
    self._known_runtime_clue_ids(executor, action["room_id"], action["character_id"]),
    allow_failure_preservation=allow_failure_preservation,
)
candidate = selection.candidate
if candidate is None:
    self._log_runtime_clue_rejections(action, selection.rejected_condition_kinds)
    return []
```

实现 `_known_runtime_clue_ids(...)` 时，联合读取该角色自身 `clues` 和本房间 `clue_shares` 对应原 clue 的 `source` 与 `clue_id`；将 `runtime:<canonical_id>` 还原为 canonical ID，保留直接等于 canonical ID 的历史 clue ID 兼容路径。

保持现有 UUID5 生成、`ON CONFLICT DO NOTHING`、`EventLog.log_event(..., action_id=...)` 和发布流程；将写入文本改为 `f"{candidate.name}：{candidate.player_text}"`，仅在两者相同或文本为空时写名称。`description` 与 `private_version` 不再进入该路径。

在有状态事务和无状态回退路径都调用该方法；成功结果传 `allow_failure_preservation=False`，非成功但已进入正常结算的结果传 `True`。这样 `failure_outcome.preserve_core` 只放开合格失败行动，不放开拒绝、异常或未确认行动。

对未知条件只写 `logger.warning` 的最小管理员诊断（房间、行动、条件拒绝码和 canonical ID）；日志中不得写线索正文或私密字段。

- [ ] **Step 4: 运行定向回归**

Run: `python -m pytest tests/server/test_progression_recovery.py tests/server/test_narrator_runtime.py::test_verified_generic_ending_completes_room_only_after_condition_match tests/server/test_reveal_ledger.py -q`

Expected: PASS；现有字典式 `RevealLedger` 行为不变，运行时线索结算不再依赖玩家提及未知名称。

- [ ] **Step 5: 提交本任务**

```bash
git add src/server/engine/resolution_pipeline.py tests/server/test_progression_recovery.py
git commit -m "fix: resolve runtime clues from action conditions"
```

### Task 3: 收紧导演上下文中的未揭示线索

**Files:**

- Modify: `tests/server/test_director_runtime.py:582-656`
- Modify: `src/server/ai/director.py:306-459`

**Interfaces:**

- Consumes: 当前的 `_compact_runtime_package(runtime_package, current_scene)`。
- Produces: 保留现有 `runtime_package["clue_dependencies"]` 键的兼容空列表，但绝不包含原始线索对象。

- [ ] **Step 1: 写出失败的导演上下文安全测试**

```python
def test_director_context_never_projects_current_scene_raw_clue_dependency(test_db):
    context = build_director_context(test_db, character, draft)
    rendered = json.dumps(context, ensure_ascii=False)
    assert context["runtime_package"]["clue_dependencies"] == []
    assert "CURRENT CLUE DESCRIPTION SECRET" not in rendered
    assert "CURRENT CLUE PRIVATE VERSION SECRET" not in rendered
    assert "CURRENT CLUE PREREQUISITE SECRET" not in rendered
```

构造带当前 `scene_id` 的线索依赖，以避免旧的“远端场景被过滤”测试掩盖泄露问题。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/server/test_director_runtime.py::test_director_context_never_projects_current_scene_raw_clue_dependency -q`

Expected: FAIL，现有 `matching_items(...)` 会把当前场景的原始线索对象投影到上下文。

- [ ] **Step 3: 实现最小安全投影**

```python
return {
    # existing safe fields
    "clue_dependencies": [],
    # existing safe fields
}
```

不要添加真实 clue ID、名称、`description`、`public_version`、`private_version`、条件数组或前置引用。权威结算已经在 Task 2 的服务端规则层完成，导演不需要这些字段才能阻止或授权线索。

- [ ] **Step 4: 运行上下文回归**

Run: `python -m pytest tests/server/test_director_runtime.py -q`

Expected: PASS，当前场景仍有安全场景、NPC、进度上下文，但没有未揭示线索负载。

- [ ] **Step 5: 提交本任务**

```bash
git add src/server/ai/director.py tests/server/test_director_runtime.py
git commit -m "fix: keep unrevealed clues out of director context"
```

### Task 4: 集成验证与真实完整剧本验收

**Files:**

- Modify: `docs/superpowers/plans/2026-08-30-global-reveal-conditions.md`（勾选完成步骤并记录命令结果）
- Verify only: `data/golden_modules/02-short-team-glass-rain/module.json`
- Verify only: `data/golden_modules/03-investigation-sandbox-lost-property/module.json`

**Interfaces:**

- Consumes: Task 1–3 的选择器、持久化和上下文隔离。
- Produces: 自动化测试证据与使用正常玩家流程的真实新房间自测证据。

- [ ] **Step 1: 跑完整定向自动化集**

Run:

```bash
python -m pytest tests/server/test_runtime_reveal_conditions.py tests/server/test_progression_recovery.py tests/server/test_director_runtime.py tests/server/test_reveal_ledger.py tests/server/test_lost_property_runtime_contract.py tests/server/test_glass_rain_runtime_contract.py -q
```

Expected: PASS。

- [ ] **Step 2: 检查未污染的工作范围**

Run:

```bash
git diff --check
git status --short
```

Expected: 本轮只显示本计划列出的文件和计划勾选变化；不暂存或修改用户已有的无关改动。

- [ ] **Step 3: 通过正常管理流程生成最新版本并开新房间**

使用当前本地服务及管理员身份，从正常剧本升级/创建房间路径生成 `雾港失物局` 的最新运行时包。只使用正常玩家的进入、行动草案、确认行动与状态读取接口；不使用房主强制揭示、直接数据库写入或隐藏管理接口。

依次验证：柜台检查得到 `brass-token`；在夜市持该前置线索向钟师傅追问得到 `token-scratch`；后续按剧本场景行动取得终局所需线索并触发结局。记录每次行动 ID、返回状态、已发现线索 source 和房间结局状态，不记录令牌或未揭示内容。

- [ ] **Step 4: 记录实际结果并提交验证文档**

将命令、通过数、真实验收的安全摘要写入本计划末尾的“执行记录”，勾选已完成步骤。

```bash
git add docs/superpowers/plans/2026-08-30-global-reveal-conditions.md
git commit -m "test: verify global clue reveal conditions"
```

## 计划自检

- 规格覆盖：Task 1 实现全剧本统一条件、OR/AND、未知拒绝和核心优先；Task 2 实现权威、私有、幂等、失败保留与管理员最小诊断；Task 3 消除导演上下文泄露；Task 4 验证自动化和真实完整剧本。
- 占位符扫描：没有 `TODO`、`TBD`、未定义的后续接口或“类似前一任务”的引用。
- 类型一致性：Task 1 的 `RuntimeClueCandidate`、`RuntimeClueSelection` 与 `select_runtime_clue(...)` 是 Task 2 的唯一新引入接口；Task 3 不依赖该接口，只收紧既有紧凑投影。
