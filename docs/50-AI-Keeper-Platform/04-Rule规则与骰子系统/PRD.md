# Rule 规则与骰子系统 PRD 初版

## 目标

提供服务端权威骰子和规则裁决能力，先稳定 COC 7e 主链路，再为多规则插件留下接口。

## 范围

包含骰子表达式、公开骰、暗骰、技能检定、成功等级、SAN、HP/MP/SAN 变化和骰子日志。不包含完整 DND/PF2E 实现、复杂插件市场和规则书版权内容分发。

## 角色

| 角色 | 权限 |
|---|---|
| 玩家 | 请求检定、查看授权结果。 |
| AI KP | 建议需要什么检定和原因。 |
| Engine | 执行权威掷骰和状态变更。 |
| 房主 | 查看公共结果和有限后台诊断。 |

## 用户故事

| 编号 | 用户故事 | 优先级 |
|---|---|---:|
| RULE-1 | 作为玩家，我能对自己的技能发起检定。 | P0 |
| RULE-2 | 作为系统，我能服务端生成骰子结果。 | P0 |
| RULE-3 | 作为 AI KP，我能建议检定但不能决定结果。 | P0 |
| RULE-4 | 作为玩家，我能在日志里查到骰子记录。 | P0 |

## 数据边界

Roll request、roll result、skill check、state mutation 和 event log 分离。骰子结果由服务端生成，状态变化由 Engine 校验后写入。暗骰结果不进入公共投影。

## 接口 / 事件方向

- REST：请求技能检定、查询角色可用技能、查询骰子日志。
- Event：`roll_requested`、`roll_resolved`、`skill_check_resolved`、`san_check_resolved`、`state_changed`。
- Rule API：保留 `systemId`、`ruleVersion`、`mechanicType`，为后续插件化准备。

## 验收标准

- 服务端生成骰子结果并写日志。
- 技能检定成功等级正确。
- 暗骰不会进入公共频道。
- AI 输出不能直接覆盖规则结果。

