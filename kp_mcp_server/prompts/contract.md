# KpResponse 合同规范

你必须返回严格的 JSON 对象，结构如下：

```json
{
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
      "permission": "direct|validate",
      "target": "目标ID（角色/房间/NPC）",
      "payload": {}
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
  "_error": null
}
```

## 字段规则

### narrative
- public 必须始终有值
- perCharacter 只填写有私有信息的角色

### rollRequests
- 只有存在不确定性的行动才提出检定
- difficulty: regular(常规)/hard(困难,半值)/extreme(极难,1/5值)
- bonusDice: 正数=奖励骰，负数=惩罚骰
- 战斗检定不可重复（不可孤注一掷）
- 理智检定不需要放在这里（由 kp_resolve_sanity 处理）

### stateMutations
- permission='direct': 叙事类效果，后端直接写（叙事文本、NPC反应、场景切换、状态标签）
- permission='validate': 数值类效果，后端掷骰+校验后写（san_loss/hp_loss/mp_loss/luck_change/gain_clue/move_location）
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
