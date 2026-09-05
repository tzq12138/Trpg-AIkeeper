# PRD-30 - 双层规则引擎架构（Strategy Pattern + JSON5 DSL）

**版本**: 1.0
**状态**: 待开发
**来源**: `规则导入.md`、PRD-01、PRD-29
**定位**: Engine 阶段三"Python 规则引擎绝对裁决"的内部架构设计，定义核心规则 Handler 注册表与剧本级 JSON5 触发器 DSL

## 1. 背景

PRD-29 §5.1 阶段三要求"Python 规则引擎绝对裁决"——暗骰、状态落库、stateVersion++，大模型零参与。但未定义规则引擎内部如何组织。实际需求是将规则分为两层：底层核心系统规则（Python 硬编码插件，如 COC 7 版 D100 检定）和剧本级业务规则（JSON5 配置，如"阅读死灵之书触发 SAN 检定"）。两层必须解耦，以便未来扩展 DND 5e 等其他规则体系。

## 2. 目标

- 建立 Strategy Pattern + Registry 的核心规则 Handler 体系。
- 定义 JSON5/受限 DSL 的剧本级触发器配置格式。
- 实现从 LLM 机制编译器输出到规则 Handler 的路由分发。
- 确保规则执行的绝对确定性：所有数值计算在 Python 内存中完成，AI 零参与。
- 支持未来扩展到 DND 5e、PF2e 等规则体系。

## 3. 范围边界

**包含**
- `BaseRuleHandler` 抽象类与 `rule_registry` 注册表。
- COC 7 版核心 Handler：`CocSkillCheckHandler`、`CocSanityCheckHandler`、`CocCombatHandler`。
- JSON5 剧本级触发器格式：`triggers[].condition` + `triggers[].mechanics[]`。
- 规则执行管线：路由分发 → 状态注入 → 计算事实 → 编译突变 → 合流给 LLM。
- `ResolutionResult` 输出 Schema（含 `cascadingStateChanges`）。

**不包含**
- DND 5e / PF2e 等其他规则体系的 Handler 实现（二期）。
- 创作者可视化规则编辑器（三期）。
- LLM 机制编译器的实现（PRD-29 阶段二）。
- 叙事渲染器的实现（PRD-29 阶段四）。

## 4. 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-30-1 | 作为 Engine 开发者，我需要每个规则机制（skill_check、sanity_check）是独立的 Handler 类，以便新增规则不修改已有代码。 | P0 |
| US-30-2 | 作为剧本创作者，我需要在 JSON 中定义"玩家阅读此书触发 SAN 检定"的规则，而不写 Python 代码。 | P0 |
| US-30-3 | 作为系统，规则引擎的数值计算必须 100% 确定性——相同输入相同输出，AI 幻觉无法干扰。 | P0 |
| US-30-4 | 作为架构师，我需要规则体系可扩展——未来支持 DND 5e 只需注册新 Handler，不改引擎核心。 | P1 |

## 5. 功能需求

### 5.1 核心 Handler 体系（Strategy Pattern + Registry）

```python
class BaseRuleHandler:
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        raise NotImplementedError

class CocSkillCheckHandler(BaseRuleHandler):
    """COC 7版标准技能检定 — D100 + 困难/极难门限 + 大成功/大失败"""
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        skill_name = params.get("skillName")
        difficulty = params.get("difficulty", "regular")
        skill_value = state.character.skills.get(skill_name, 0)

        # 计算门限
        target = skill_value
        if difficulty == "hard": target = skill_value // 2
        elif difficulty == "extreme": target = skill_value // 5

        # 暗骰
        roll = random.randint(1, 100)

        # 判定成功等级
        if roll == 1:
            level = "critical_success"
        elif roll >= 96 and skill_value < 50:
            level = "fumble"
        elif roll == 100:
            level = "fumble"
        elif roll <= target:
            level = "success"
        else:
            level = "failure"

        return RuleResult(
            is_success=(level in ["success", "critical_success"]),
            metadata={"roll": roll, "target": target, "level": level}
        )
```

**注册表**（引擎启动时初始化）：
```python
rule_registry: dict[str, BaseRuleHandler] = {
    "skill_check": CocSkillCheckHandler(),
    "sanity_check": CocSanityCheckHandler(),
    "combat_damage": CocCombatHandler(),
    "luck_check": CocLuckCheckHandler(),
}
```

**扩展点**：未来支持 DND 5e 时，注册 `DndSkillCheckHandler`（D20 + 优势/劣势）即可，不改引擎核心。

### 5.2 剧本级触发器（JSON5 DSL）

**安全约束**：创作者只能配置 JSON 描述符，**绝对禁止**上传 Python 脚本（防沙箱逃逸）。

**触发器格式**（定义在 `scenario_assets.json` 的 `scene.triggers` 中）：
```json
{
  "nodeId": "scene_library_book",
  "triggers": [
    {
      "condition": { "$action": "read_item", "itemId": "book_necronomicon" },
      "mechanics": [
        {
          "type": "sanity_check",
          "params": { "successLoss": "1d3", "failureLoss": "1d10" }
        },
        {
          "type": "apply_patch",
          "params": { "path": "/skills/cthulhu_mythos", "op": "add", "value": 5 }
        }
      ]
    }
  ]
}
```

**执行逻辑**：Engine 处理玩家动作时，先遍历当前 Scene 的 `triggers`。条件命中后，按序调用 `rule_registry[type]` 中的 Handler 结算。

### 5.3 规则执行管线（与 PRD-29 阶段三对接）

```
[LLM 机制编译器输出] → { triggeredMechanic: "skill_check", skillName: "射击", difficulty: "hard" }
        │
        ▼
┌─────────────────────────────────┐
│ 1. 路由分发 (Dispatch)           │  rule_registry["skill_check"] → CocSkillCheckHandler
├─────────────────────────────────┤
│ 2. 状态注入 (Injection)          │  注入 CharacterNode (HP/SAN/技能表) 作为只读状态
├─────────────────────────────────┤
│ 3. 计算事实 (Compute Fact)       │  Handler 掷出 78, 判定 failure
├─────────────────────────────────┤
│ 4. 编译突变 (Compile Mutation)   │
│    - Host 演出: RevealStep       │  { kind: 'roll', payload: { rolledValue: 78, resultType: 'failure' } }
│    - Player 补丁: RFC 6902 Patch │  [{ op: "replace", path: "/hp/current", value: 8 }]
├─────────────────────────────────┤
│ 5. 合流给 LLM (Merge to LLM)   │  [动作: 射击, 难度: 困难, 结果: 78/50 失败] → 叙事渲染器
└─────────────────────────────────┘
```

### 5.4 ResolutionResult 输出 Schema

```python
@dataclass
class RuleResult:
    is_success: bool
    metadata: dict  # { "roll": 78, "target": 50, "level": "failure" }
    mutations: list[dict]  # RFC 6902 patches
    reveal_steps: list[dict]  # Host 演出 steps
    cascading_state_changes: list[str]  # 级联后果描述（供 LLM 叙事渲染器使用）
```

**关键字段 `cascading_stateChanges`**：解决 PRD-29 Bug 1（Fact Lag）。当规则执行导致 HP 归零、SAN 崩溃等重大状态变更时，Handler 必须将级联后果写入此字段，Engine 在组装阶段四 Prompt 时强制注入。

## 6. 接口/事件依赖

| 类型 | 名称 | 用途 |
|------|------|------|
| Type | `BaseRuleHandler` | 规则 Handler 抽象基类 |
| Type | `RuleResult` | Handler 输出（含 mutations、reveal_steps、cascading_state_changes） |
| Type | `GameState` | 注入 Handler 的只读状态（角色属性、场景实体、背包） |
| Registry | `rule_registry` | 机制名 → Handler 的映射表 |
| Config | `scenario_assets.json` → `triggers` | 剧本级触发器定义 |
| Event | `s2c_reveal_transaction` | Handler 生成的 Host 演出 steps |
| Event | `s2c_state_patch` | Handler 生成的 Player RFC 6902 补丁 |

## 7. 状态与错误处理

- Handler 不存在（`rule_registry` 未注册该机制）：降级为 `auto_success`，记录 `rule_handler_not_found`。
- Handler 执行异常（如角色属性缺失）：返回 HTTP 500，记录 `rule_execution_error`，不发送任何投影。
- JSON5 触发器格式错误（`scenario_assets.json` 解析失败）：跳过该触发器，记录 `trigger_parse_error`，不阻塞游戏。
- `apply_patch` 的 path 不存在：静默忽略该 mutation，记录 `patch_path_not_found`。
- 触发器条件匹配失败：正常跳过，不记录（这是预期行为）。

## 8. 验收标准

- `CocSkillCheckHandler` 单测覆盖：大成功(1)、大失败(100/96+)、普通成功、普通失败、困难门限、极难门限。
- `CocSanityCheckHandler` 单测覆盖：成功扣 1d3、失败扣 1d10、SAN 归零触发疯狂。
- JSON5 触发器端到端：玩家阅读 `book_necronomicon` → 触发 `sanity_check` → 扣 SAN + 获得 Cthulhu 神话技能。
- `rule_registry` 扩展性验证：注册自定义 Handler 后可被触发器路由调用。
- `cascading_state_changes` 正确传递到 PRD-29 阶段四的 Prompt 中。

## 9. 测试场景

1. 玩家提交 `skill_check`（侦查，普通难度，技能值 60），暗骰 45 → 成功 → `RuleResult.is_success = True`。
2. 玩家提交 `skill_check`（斗殴，困难难度，技能值 80），暗骰 50 → 失败（困难门限 40）→ HP 扣减 → `cascading_state_changes` 含 "HP 归零"。
3. 剧本触发器：玩家动作 `read_item` + `itemId: book_necronomicon` → 命中 → 执行 `sanity_check` + `apply_patch`。
4. 注册 `DndSkillCheckHandler`（D20 + 优势）后，`rule_registry["dnd_skill_check"]` 可被路由调用。
5. 触发器 JSON 格式错误 → 跳过 + 日志，不影响其他触发器。

## 10. 风险依赖

- 依赖 PRD-29 阶段二 LLM 机制编译器输出的 `triggeredMechanic` 字段格式正确。
- `scenario_assets.json` 的触发器语法需要文档和示例——创作者需要明确的编写指南。
- `cascading_state_changes` 的 Prompt 注入逻辑需与 PRD-29 阶段四的 Prompt 模板协调。
- 未来 DND 5e 扩展时，`GameState` 的数据结构可能需要调整（DND 有法术位、先攻等概念）。
