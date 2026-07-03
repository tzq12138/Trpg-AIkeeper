# 游戏状态持久化与变更总线计划

## Summary
- 采用“表权威 + 事件审计 + 检查点恢复”模型。
- 原始剧本、原始角色卡不直接污染；每个房间生成独立运行态。
- 账号名下保留长期角色档案；进房间时生成本局角色状态；结算后只把永久变化写回长期档案。
- 所有游戏中状态变更统一经过 `StateService`，负责写库、递增版本、写事件、发投影、触发检查点。

## API / Interfaces
- 新增 `StateService.apply_change(room_id, actor, changes, reason)`：
  - 输入统一 `StateChangeSet`，包含角色、场景、地图、线索、物品、遭遇、房间状态变更。
  - 一个事务内完成：验证权限、写权威表、递增 `room.state_version` 和实体版本、写 `events`。
  - 事务提交后通过 dispatcher 推送 WebSocket；推送失败不影响持久化，重连靠事件补发。
- 新增长期角色档案：
  - `character_profiles`：账号持有的长期角色卡、基础属性、技能、经历、永久伤病、可继承物品。
  - 现有 `characters` 保留为“某房间里的角色实例”，新增 `profile_id` 关联长期档案。
  - 新增 `character_runtime_state`：本局 HP/SAN/MP/Luck、状态标签、临时修正、当前可见状态、实体版本。
- 新增房间场景运行态：
  - `room_scene_state`：当前场景、已访问场景、已触发 trigger、公开事实、场景变量、当前素材/BGM、实体版本。
  - 原始 `scenarios/scenario_assets/scenario_maps` 只作为模板，不写入本局进度。
- 扩展版本：
  - 保留 `rooms.state_version` 作为全局同步版本。
  - 角色运行态、场景运行态、地图状态、遭遇、遭遇参与者都带实体 `version`。

## Key Changes
- **角色状态**
  - 导入/选择车卡时写入长期 `character_profiles` 或复用已有 profile。
  - 加入房间时复制 profile 生成本局 `characters + character_runtime_state`。
  - 本局 HP/SAN/MP/Luck、临时状态、当前位置、临时物品都只改运行态。
  - 永久变化用 `permanent=true` 标记，战役结束时写入 profile；临时损耗默认不继承。
- **技能和属性**
  - 基础属性、技能原值保存在 profile/sheet snapshot。
  - 临时加减值和本局覆盖值放运行态。
  - 技能成长、永久属性变化、永久疯狂、重要伤病作为永久变更候选，结算时写回 profile。
- **场景状态**
  - 当前场景、探索进度、公开事实、已触发事件、场景变量、当前展示图片/BGM 都存在 `room_scene_state`。
  - 场景切换、触发器命中、素材播放、地图节点揭示都走 `StateService`。
- **地图和位置**
  - 继续使用 `room_map_state` 与 `character_map_positions`，但所有移动、探索、隐藏/显示节点统一经 `StateService`。
  - 玩家位置是角色运行态的一部分，同时保持地图表方便查询。
- **事件与同步**
  - 每次状态变更必须产生审计事件和对应前端投影：Host HUD、Player state patch、公共观察、地图更新等。
  - 前端刷新或断线后先读权威状态快照，再按 `roomSequence` 补事件。
- **检查点**
  - 自动检查点：开局、回合结算、场景切换、战斗/追逐结束、战役结束。
  - 手动检查点：Admin/房主可保存和回滚。
  - 回滚恢复权威表后写一条系统事件，前端重新同步快照。

## Test Plan
- 状态写入测试：HP/SAN/物品/线索/位置/场景变量通过 `StateService` 写入后，表状态、事件日志、版本号一致。
- 并发测试：旧版本提交返回冲突；实体版本能定位是角色、地图还是场景冲突。
- 恢复测试：自动检查点和手动检查点能恢复角色、地图、场景、遭遇、事件。
- 继承测试：临时 HP/SAN 损耗不写回长期角色档案；永久伤病、技能成长、重要物品可写回。
- 前端同步测试：Player/Host 刷新后能从快照恢复，再接收后续事件；不再出现“库里改了但前端没收到”。

## Assumptions
- 本轮不做完整事件溯源重构，事件用于审计、同步和回放，当前状态仍以关系表为权威。
- 不把所有状态塞进一个大 JSON；JSON 只用于角色卡原始结构、临时 modifiers、场景变量等弹性字段。
- 旧 `characters.xlsx_data` 可先作为兼容快照保留，逐步迁到 profile + runtime state。
- 正式迁移框架仍不引入，按现有开发库策略使用幂等建表/补列。
