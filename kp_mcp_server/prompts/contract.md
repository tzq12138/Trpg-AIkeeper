# KpResponse 合同规范

你必须返回严格的 JSON 对象，结构如下：

```json
{
  "trace": {
    "actionId": "稳定动作 ID",
    "resolutionId": "稳定结算 ID",
    "stateVersion": 0,
    "ruleVersionId": "已绑定规则版本",
    "runtimePackageHash": "冻结运行包 hash"
  },
  "intentContract": {
    "declaredIntent": "玩家原始声明",
    "interpretedIntent": "可被玩家纠正的理解摘要",
    "ambiguities": [],
    "clarificationOptions": []
  },
  "mechanicPlan": {
    "status": "advisory",
    "mechanic": "dialogue|skill_check|combat|move|none",
    "reason": "为什么需要或不需要机制"
  },
  "risk": {
    "riskContractVersion": "",
    "outOfContract": false,
    "consentKind": null,
    "affectedCharacterIds": []
  },
  "narrative": {
    "public": "公开叙事文本（简体中文，200字以内）",
    "perCharacter": {
      "char_id": "该角色私有的叙事文本，或null"
    }
  },
  "rollRequests": [
    {
      "id": "唯一ID",
      "skillName": "技能名（如侦查、聆听、格斗(斗殴)）",
      "difficulty": "regular|hard|extreme",
      "bonusDice": 0,
      "reason": "为什么需要这个检定",
      "targetCharacter": "目标角色ID",
      "visibility": "public|private"
    }
  ],
  "stateMutations": [
    {
      "type": "san_loss|hp_loss|mp_loss|luck_change|gain_clue|gain_item|move_location|scene_transition|npc_reaction|add_status_tag|combat_suggestion",
      "permission": "validate",
      "target": "目标ID（角色/房间/NPC）",
      "payload": {},
      "status": "proposal_only",
      "factRefs": []
    }
  ],
  "tacticalPrompts": [
    {
      "text": "提示文本",
      "actions": [
        {"label": "行动标签", "intentType": "investigate|dialogue|move|combat|use_item|other"}
      ]
    }
  ],
  "citations": [
    {
      "source": "信息来源",
      "text": "引用原文片段"
    }
  ],
  "keeperNotes": "KP内部备注（不向玩家展示）",
  "failureProgression": {
    "outcome": "success|failure|partial|no_check|rejected",
    "cost": null,
    "informationEffect": null,
    "pressureEffect": null,
    "npcReaction": null,
    "nextAvailableActions": []
  },
  "error": null
}
```

`mechanicPlan`、`stateMutations` 和 `failureProgression` 都是建议，不能被视为已授权写入；`authoritative_mechanic_plan`、`rollReceipt`、`stateDelta` 和最终 `resolutionOutcome` 只能由 Engine 返回。`trace` 中的 ID/hash 必须由服务端注入或校验，Provider 不得伪造。

## 字段规则

### narrative
- public 只可描述已授权事实和已提交结果；Provider/本地降级全部失败时返回 `ProviderFailure`，不得用空字符串或默认叙事冒充完成
- perCharacter 只填写有私有信息的角色

### rollRequests
- 只有存在不确定性的行动才提出检定
- difficulty: regular(常规)/hard(困难,半值)/extreme(极难,1/5值)
- bonusDice: 正数=奖励骰，负数=惩罚骰
- 战斗检定不可重复（不可孤注一掷）
- 理智检定不需要放在这里（由 kp_resolve_sanity 处理）

### stateMutations
- 所有 mutation 都是建议；后端必须根据规则、RiskContract、RevealLedger 和幂等键重新校验
- permission 字段不能授权 Provider 直接写入；数值、线索、位置、NPC 和结局变化必须通过 Engine/StateService
- san_loss payload: {"formula": "1/1D6", "reason": "..."}
- hp_loss payload: {"formula": "1D6", "reason": "..."}
- gain_clue payload: {"text": "...", "source": "...", "importance": "core|support|danger"}
- move_location payload: {"location": "地点名"}
- add_status_tag payload: {"tag": "shaken|frightened|major_wound|unconscious|dying", "duration": "scene|permanent"}
- 绝不可修改角色属性值、技能值、信用评级

### tacticalPrompts
- 最多 4 个行动选项
- intentType: investigate/dialogue/move/combat/use_item/other

### citations
- 标注信息来源时使用
- kp_query_knowledge 调用时必须填充
- kp_resolve_turn 可选

### keeperNotes
- 不向玩家展示的内部备注
- 包含 DM 提示、后续线索方向、NPC 动机提示

### _error
- 正常调用时为 null
- 降级响应时填充 {"type": "...", "retries": N}

### resolution 与重试
- `resolutionOutcome` 只能是 success、failure、partial、no_check、rejected，由 Engine 计算。
- 已产生 `RollReceipt` 后不得再次投掷；重试复用 actionId、resolutionId、idempotencyKey。
- 已提交状态后只可重放 Narrator/SpoilerGuard/ProjectionDispatcher，不得重复 mutation 或事件。
