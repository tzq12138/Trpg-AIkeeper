# Rule 规则与骰子系统 PRD

## 目标

Rule v1 的目标是稳定 COC 7e 主链路：玩家提交意图，AI 或本地编译器只决定“需要什么机制”，Python RuleExecutor 执行权威数学裁决，产出可追溯的骰子结果、状态 mutation 和投影步骤。

第一轮不追求完整多规则平台，而是先统一当前已经存在的技能检定、SAN/HP/Luck、剧本触发器、战斗/追逐 Handler 和前端展示口径。

## 产品定位

Rule 是 Engine 内部的规则事实层。它接收 `PlayerIntent + MechanicCompileResult + Character/Inventory/ScenarioAssets`，输出 `ResolutionResult`。Rule 不直接保存聊天消息，不直接修改数据库真相，不替代 StateService。

## 角色与权限

| 角色 | 可做 | 不可做 |
|---|---|---|
| Player | 请求技能检定、行动检定、战斗/追逐动作，查看授权结果 | 提交骰点、目标值、成功等级作为权威结果 |
| AI-Keeper | 建议检定类型、技能名、难度、原因、可选 bonusDice | 直接决定骰点、直接扣 HP/SAN、覆盖 Python 结果 |
| Engine | 调用 RuleExecutor，记录 action result，驱动 State/Projection | 跳过 Rule 直接采纳 AI 数值 |
| Host | 查看公开骰、播放规则结果、做有限急救 | 在 Host 端改写已结算规则事实 |
| Admin | 排查规则错误和日志 | 把测试/后台接口暴露给普通玩家 |

## v1 范围

| 范围 | 说明 |
|---|---|
| COC D100 检定 | regular/hard/extreme、成功等级、大成功、大失败。 |
| 奖励/惩罚骰 | 保留并接入主链路，统一参数为 `bonusDice`。 |
| SAN/HP/Luck | 通过 Handler 产出 mutation 和 cascading state changes。 |
| 机制编译 | DeepSeek 失败时 Python fallback，输出结构化 `MechanicCompileResult`。 |
| 剧本触发器 | 支持 `scenario_assets.scenes[].triggers[]` 与全局 triggers。 |
| 战斗/追逐 v1 | 使用已注册 encounter handler，保持最小可用。 |
| 投影输出 | 规则结果进入 `s2c_reveal_transaction`、`s2c_state_patch`、`s2c_action_completed`。 |
| 回归测试 | 固化当前核心规则测试，并补足口径漂移测试。 |

## v1 不做

- 不实现完整 DND 5e、PF2e、双规则共存。
- 不做创作者可视化规则编辑器。
- 不允许上传或执行自定义 Python 规则脚本。
- 不把 `/api/player/skill-check` 当作长期主入口。
- 不做 3D 骰子动画和复杂物理骰。

## 核心数据结构

### PlayerIntent

玩家输入的权威入口仍是 `POST /api/player/intent`：

```json
{
  "action_id": "<uuid>",
  "intent_type": "skill_check",
  "declared_intent": "使用技能：侦查",
  "base_state_version": 12,
  "params": {
    "skillName": "侦查",
    "difficulty": "regular",
    "bonusDice": 0
  }
}
```

### MechanicCompileResult

AI 或 Python fallback 只能输出机制建议：

```json
{
  "triggeredMechanic": "skill_check",
  "skillName": "侦查",
  "difficulty": "regular",
  "itemConsumed": false,
  "consequence": {}
}
```

### RuleResult

单个 Handler 输出规则事实：

```json
{
  "is_success": true,
  "metadata": {
    "dice": "d100",
    "roll": 42,
    "target": 60,
    "skill_name": "侦查",
    "success_level": "regular"
  },
  "mutations": [],
  "reveal_steps": [
    {
      "kind": "roll",
      "dice": "d100",
      "result": 42,
      "target": 60,
      "skillName": "侦查",
      "successLevel": "regular"
    }
  ],
  "cascading_state_changes": []
}
```

### ResolutionResult

RuleExecutor 合并多个 Handler 后输出给 pipeline：

```json
{
  "actionId": "<uuid>",
  "roomId": "<room_id>",
  "characterId": "<character_id>",
  "mechanic": "skill_check",
  "isSuccess": true,
  "metadata": {},
  "mutations": [],
  "revealSteps": [],
  "cascadingStateChanges": [],
  "narrative": ""
}
```

## 主流程

1. Player 通过角色卡、战术按钮或行动文本提交 `POST /api/player/intent`。
2. Engine 用 `X-Room-Token` 解析角色身份，写入 actions，进入 resolving。
3. `MechanicCompiler` 根据 intent、场景和角色输出 `MechanicCompileResult`。
4. `RuleExecutor` 读取角色卡技能、背包和剧本触发器，决定实际 mechanics。
5. 对每个 mechanic 调用 `rule_registry` 中的 Handler。
6. Handler 服务端掷骰，计算成功等级，生成 metadata、reveal_steps、mutations。
7. Pipeline 保存 action result，投影 Host 事务、Player 状态补丁、Action Completed。
8. 若有 mutations，StateService 作为唯一状态写入者应用变更。
9. Journal/Archive 通过 action result 和 events 提供复盘。

## 接口方向

| 接口/事件 | 状态 | 用途 |
|---|---|---|
| `POST /api/player/intent` | 主入口 | 所有权威规则检定必须走这里。 |
| `POST /api/player/skill-check` | 兼容/降级 | 即时返回独立检定，不进入事务和状态写入。 |
| `s2c_reveal_transaction` | 已用 | Host 播放 roll、status_delta、narrative_text。 |
| `s2c_state_patch` | 已用 | 玩家端接收状态变化。 |
| `s2c_action_completed` | 已用 | 玩家端解锁并展示检定结果。 |
| `GET /api/player/archive/skill-checks` | 已用 | 查询自身 skill_check actions。 |

## 成功等级口径

v1 应统一为：

| 枚举 | 含义 |
|---|---|
| `critical` | 掷出 1。 |
| `extreme` | 掷骰小于等于技能值五分之一。 |
| `hard` | 掷骰小于等于技能值二分之一。 |
| `regular` | 掷骰小于等于技能值。 |
| `failure` | 未达到目标值。 |
| `fumble` | 掷出 100；或低技能大失败规则命中。 |

当前 `CocSkillCheckHandler` 仍返回 `critical_success/success/failure/fumble`，需要在 DeepSeek 第一批收敛，不要让前端把未知等级默认为 regular。

## 权限与安全边界

- 权威骰点只能由服务端生成。
- `skillValue` 应优先从角色卡读取；前端传入值只作为兼容或显示辅助，不应长期作为权威来源。
- AI 输出的 `rollRequests` 只是请求，不是结果。
- 暗骰、私密骰、私密状态变化必须走 Projection 的服务端受众过滤。
- 剧本触发器只能是 JSON 描述，不允许任意代码执行。
- Rule Handler 异常时 action 必须 rejected，并发送 `s2c_action_completed` 解锁玩家端。

## 验收标准

| 场景 | 验收 |
|---|---|
| 技能检定 | 玩家提交 skill_check 后，服务端生成 roll，玩家收到 `s2c_action_completed`。 |
| Host 投影 | Host 收到包含 roll step 的 `s2c_reveal_transaction`。 |
| 成功等级 | `critical/extreme/hard/regular/failure/fumble` 全链路一致。 |
| SAN 触发器 | 使用指定物品命中剧本 trigger，执行 SAN 检定并产生 mutation。 |
| AI 边界 | DeepSeek 返回非法/异常时 fallback 到 Python 编译器。 |
| 前端防作弊 | 前端提交 roll/result 字段不会被采纳为权威结果。 |
| 状态写入 | HP/SAN mutation 由 StateService 应用，Rule 不直接落库。 |

## 当前风险

| 风险 | 影响 | 优先级 |
|---|---|---:|
| `skill_check.py` 与 `CocSkillCheckHandler` 成功等级不一致 | 前端展示、日志、NarrativeProvider 容易错判 | P0 |
| `s2c_action_completed` 使用 `level` 而非统一 `success_level/successLevel` | PlayerCharacter 可能把真实等级退回 regular | P0 |
| 主 Handler 不支持 bonus_dice | AI/前端传入 bonusDice 后无效 | P0 |
| fallback `/skill-check` 不写 action/event | 结果不可复盘，容易和主链路混淆 | P1 |
| `parse_dice` 只支持 `XdY` | 无法表达常见 `1d6+1` SAN/伤害 | P1 |
| Handler 直接用 random，无 RollRecord | 事后审计随机来源较弱 | P2 |

