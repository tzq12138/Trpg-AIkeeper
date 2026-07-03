# 战斗/追逐最小可用状态机计划

## Summary
- 做 Host 可控的“遭遇系统”：AI 发现危险后给 Host 建议，Host 确认后开启战斗或追逐。
- v1 做轻量双模块：战斗和追逐共用参与者、回合、距离带、状态标签；不一次性实现完整 COC 全细则。
- 规则接口按完整 COC 预留，首批只实现攻击/闪避/伤害、追赶/逃脱/距离变化。
- 遭遇接入场景回合制：每轮参与者提交行动，全员提交或 Host 跳过后统一结算。
- 玩家端提供“战术按钮 + 自由输入”，既稳定识别常用动作，也保留跑团表达。

## Key Changes
- 新增遭遇状态机：
  - 新增 `encounters`：`encounter_id`、`room_id`、`type=combat/chase`、`status=suggested/active/resolved/cancelled`、当前轮次、摘要。
  - 新增 `encounter_participants`：角色/NPC、阵营、HP/SAN、DEX、MOV、当前位置、距离带、状态标签、是否本轮已行动。
  - 新增 `encounter_actions` 或复用 `actions.params.encounterId`，把攻击、闪避、逃跑、追赶等行动挂到当前遭遇。
  - 遭遇状态只通过规则管线或 Host 明确操作修改，不由 AI 任意写数据库。

- AI 建议，Host 确认：
  - AI 在叙事或回合结算中可输出 `encounter_suggestion`，例如“可能进入追逐/战斗”。
  - 后端写入 `encounters.status=suggested`，HostStage 战斗/追逐 tab 显示建议卡。
  - Host 可选择参与者、类型、初始距离带、NPC 数据后确认开启；也可拒绝建议。
  - Host 支持快速创建 NPC/敌人：名称、HP、DEX、MOV、主要技能、伤害表达式、备注。

- 战斗 v1 规则：
  - 支持动作：攻击、闪避、防御/掩护、协助、逃离、待机。
  - 攻击使用现有 `skill_check`，成功后按武器/默认伤害表达式调用 `combat_damage`。
  - 闪避用角色闪避技能；v1 先做“攻击成功且闪避成功则不受伤”的简化对抗。
  - HP 归零、重伤、昏迷/濒死先用状态标签记录，不展开完整医疗/濒死细则。
  - 预留完整 COC 细则字段：反击、护甲、火器连射、困难/极难对抗、贯穿、故障值、近战武器、弹药。

- 追逐 v1 规则：
  - 使用抽象距离带：`engaged`、`near`、`short`、`medium`、`long`、`escaped`。
  - 支持动作：追赶、逃跑、阻挡、制造障碍、绕路、协助、待机。
  - 追赶/逃跑用 MOV + 技能检定决定距离带变化。
  - 障碍先用简单难度和技能名表达，不做完整逐段 chase track。
  - 逃脱条件：距离带达到 `escaped` 或 Host 手动结束追逐。

- 前端体验：
  - HostStage 战斗/追逐 tab 替换静态骨架，显示遭遇建议、当前遭遇、参与者、距离带、HP/SAN、状态、行动提交情况。
  - Host 可确认/拒绝 AI 建议、快速创建 NPC、跳过未行动参与者、结束遭遇。
  - Player 行动页在遭遇中显示战术按钮：攻击、闪避、逃跑、追赶、协助、待机；按钮提交标准化 `intent_type` 和 params。
  - 保留自由输入，AI/机制编译器尝试识别为遭遇动作；识别失败降级为普通叙事行动。

## API / Interfaces
- 新增 Host API：
  - `GET /api/rooms/{room_id}/encounters/current`
  - `POST /api/rooms/{room_id}/encounters/{encounter_id}/confirm`
  - `POST /api/rooms/{room_id}/encounters/{encounter_id}/reject`
  - `POST /api/rooms/{room_id}/encounters/{encounter_id}/participants`
  - `PATCH /api/rooms/{room_id}/encounters/{encounter_id}/participants/{participant_id}`
  - `POST /api/rooms/{room_id}/encounters/{encounter_id}/end`

- 新增/扩展事件：
  - `s2c_encounter_suggested`
  - `s2c_encounter_started`
  - `s2c_encounter_updated`
  - `s2c_encounter_resolved`

- 扩展 `PlayerIntent.intent_type`：
  - `combat_action`
  - `chase_action`
  - `system_skip`

- 标准 params：
  - `encounterId`
  - `actionKind`
  - `targetId`
  - `skillName`
  - `weaponId`
  - `damage`
  - `distanceBand`

## Test Plan
- 后端：
  - AI 建议遭遇后创建 `suggested` encounter，不影响当前普通回合。
  - Host 确认后遭遇变为 `active`，参与者写入成功。
  - 玩家提交攻击/闪避/逃跑/追赶行动后进入当前场景回合。
  - 全员提交后统一结算遭遇行动，并发送 encounter 更新事件。
  - 攻击成功会产生伤害 patch；闪避成功可抵消伤害。
  - 追逐成功会改变距离带；达到 `escaped` 可结束追逐。
  - Host 跳过未行动参与者后本轮可继续结算。
  - NPC 快速创建、状态标签、Host 手动结束遭遇都能持久化。

- 前端：
  - `npm run build` 通过。
  - Host 能看到 AI 遭遇建议并确认开启。
  - Host 能添加 NPC、查看参与者状态、跳过未行动者、结束遭遇。
  - Player 遭遇中能看到战术按钮并提交行动。
  - WS 更新后 Host/Player 都能看到 HP、距离带、状态变化。

## Assumptions
- v1 是最小可用状态机，不宣称完整 COC 战斗/追逐规则完成。
- 完整 COC 细则作为接口和数据结构预留，后续逐项补：反击、护甲、火器连射、弹药、故障值、完整追逐障碍链。
- 遭遇内部继续接入场景回合制，不另起独立先攻逐个行动系统。
- Host 保持最终控制权：AI 只能建议开启遭遇，不能自动把房间切入战斗/追逐。
