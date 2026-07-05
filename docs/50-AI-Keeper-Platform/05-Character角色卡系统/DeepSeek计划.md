# Character 角色卡系统 DeepSeek 计划初版

## 执行定位

Character 后续实现优先修“角色进入房间后，数据能被规则、状态和投影一致使用”的主链路。第一批不做角色市场、头像素材、完整成长系统和多规则大抽象。

DeepSeek 执行前必须先查看当前代码，尤其是 `src/server/player/router_player.py`、`src/server/engine/state_service.py`、`src/server/host/hud_builder.py`、`src/server/scenario/xlsx_parser.py`、`src/client/src/pages/PlayerJoinPage.tsx`、`src/client/src/pages/PlayerCharacter.tsx`。

## 全局约束

- 先运行 `git status --short`，只改本批明确相关文件。
- 保留现有 `/join` 兼容入口，但新主链路以 `/join-with-character` 为准。
- `characters.xlsx_data` 是静态卡快照，战局变化以 `character_runtime_state` 为准。
- 玩家不能直接写 HP/SAN/MP/Luck、技能值或状态标签。
- Host 只能审批和查看授权公开状态，不承载规则结算。
- AI 只读裁剪后的角色上下文，不能直接落库写角色状态。
- 修改前端角色页时必须同步处理当前中文乱码文案。

## Batch Character-0：现状核对与乱码风险收敛

| 项 | 内容 |
|---|---|
| 目标 | 建立角色链路现状清单，确认接口、状态枚举、页面乱码、测试覆盖 |
| 允许改的文件方向 | 文档、必要的前端文案文件；不改业务逻辑 |
| 建议检查 | `rg -n "pending_approval|joined|left|active|character_runtime_state|skill_value" src tests` |
| 验收命令 | `python -m pytest tests/server/test_character_join_import.py tests/server/test_xlsx_parser.py -q` |
| 禁止事项 | 不在核对批次里顺手重构路由或迁移表结构 |

产出要求：

- 列出角色来源：upload、preset、template、builder、copy。
- 列出静态卡和运行态各自被哪些接口读取。
- 标出乱码页面和用户可见错误文案位置。

## Batch Character-1：XLSX 解析、预览与质量报告

| 项 | 内容 |
|---|---|
| 目标 | 让 XLSX 预览和导入能明确说明字段来源、缺失字段和默认值 |
| 允许改的文件方向 | `src/server/scenario/xlsx_parser.py`、`src/server/scenario/character_presets.py`、`tests/server/test_xlsx_parser.py`、`tests/server/test_character_join_import.py` |
| 验收命令 | `python -m pytest tests/server/test_xlsx_parser.py tests/server/test_character_join_import.py -q` |
| 禁止事项 | 不把解析失败静默变成默认角色；不把所有未知数字字段都无条件当技能 |

验收点：

- 合法 CY20 类 COC 卡仍能解析。
- 键值表仍能解析。
- 缺 HP/SAN/MP/Luck 时返回可展示的默认来源说明。
- 损坏文件返回 400，且不创建角色。

## Batch Character-2：入房建卡、多来源选择与所有权校验

| 项 | 内容 |
|---|---|
| 目标 | 加固 `join-with-character` 的来源互斥、预设占用、模板读取、复制角色所有权 |
| 允许改的文件方向 | `src/server/player/router_player.py`、`src/server/router_rooms.py`、`tests/server/test_character_join_import.py`、`tests/server/test_room_security.py` |
| 验收命令 | `python -m pytest tests/server/test_character_join_import.py tests/server/test_room_security.py -q` |
| 禁止事项 | 不允许通过 `character_id` 复制别人角色；不允许一个请求同时带多个角色来源 |

验收点：

- 同房间预设卡重复选择返回 409。
- 复制账号角色必须是同账号，复制无账号角色必须持有原 `player_token`。
- 活跃房间加入角色状态为 `pending_approval`。
- 大厅快照不包含 token、完整 `xlsx_data`、私密背景。

## Batch Character-3：运行态权威与玩家角色 DTO

| 项 | 内容 |
|---|---|
| 目标 | 让玩家 `/character`、`/sync`、Host HUD 对 HP/SAN/MP/Luck 使用一致运行态 |
| 允许改的文件方向 | `src/server/player/router_player.py`、`src/server/host/hud_builder.py`、`src/server/engine/state_service.py`、`tests/server/test_player_runtime_state.py`、`tests/server/test_state_service.py` |
| 验收命令 | `python -m pytest tests/server/test_player_runtime_state.py tests/server/test_state_service.py tests/server/test_player_features.py -q` |
| 禁止事项 | 不回写 `xlsx_data` 来模拟战局状态；不让前端覆盖运行态 |

验收点：

- StateService 修改 HP 后，`GET /api/player/character` 返回新 HP。
- 运行态缺失时可以懒初始化或安全回退到静态卡。
- `stateVersion` 与角色运行态版本能支持前端刷新判断。
- Host HUD 和玩家角色页展示同一组当前值。

## Batch Character-4：技能检定权威来源

| 项 | 内容 |
|---|---|
| 目标 | 技能检定从服务端角色卡读取技能值，前端传值只能作为展示或校验辅助 |
| 允许改的文件方向 | `src/server/player/router_player.py`、`src/server/engine/skill_check.py`、规则处理器、`tests/server/test_player_features.py`、`tests/server/test_player_intent.py` |
| 验收命令 | `python -m pytest tests/server/test_player_features.py tests/server/test_player_intent.py -q` |
| 禁止事项 | 不信任玩家请求里的任意 `skill_value`；不在 Character 模块内复制整套规则算法 |

验收点：

- 玩家提交技能名后，后端能从自己的角色卡读取技能值。
- 提交不存在技能时返回明确错误或走默认基础值规则。
- 兜底 `/skill-check` 若保留，必须标注兼容路径并限制权威语义。

## Batch Character-5：大厅审批、ready 与公共摘要

| 项 | 内容 |
|---|---|
| 目标 | 补齐进行中加入审批 UI/测试，确保 ready 和成员状态同步稳定 |
| 允许改的文件方向 | `src/server/host/router_host.py`、`src/server/player/router_player.py`、`src/client/src/pages/HostLobby.tsx`、`src/client/src/pages/PlayerJoinPage.tsx`、`tests/server/test_host_room_lifecycle.py` |
| 验收命令 | `python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_rooms.py -q`；前端改动补跑 `cd src/client && npm run build` |
| 禁止事项 | 不把未批准角色计入正常开局和回合；不在大厅摘要里泄露完整角色卡 |

验收点：

- 活跃房间新角色显示为等待审批。
- Host approve/reject 后大厅同步。
- ready 切换广播 `s2c_room_lobby_snapshot`。
- Room 开局只考虑已加入且未离开的角色。

## Batch Character-6：账号恢复、长期档案与增长边界

| 项 | 内容 |
|---|---|
| 目标 | 明确账号角色列表、恢复 session、profile 写入与长期成长的边界 |
| 允许改的文件方向 | `src/server/player/router_player.py`、`src/server/router_auth.py`、`src/server/db_adapter.py`、`tests/server/test_auth.py`、新增角色档案测试 |
| 验收命令 | `python -m pytest tests/server/test_auth.py tests/server/test_character_join_import.py -q` |
| 禁止事项 | 不把长期成长系统一次性塞进 MVP；不导出或返回 player token 给非拥有者 |

验收点：

- 登录账号只能看到自己的角色列表。
- `restore-session` 只能恢复本账号角色。
- profile 初始化失败不影响入房主链路，但要有日志和后续修复入口。

## Batch Character-7：端到端回归

| 项 | 内容 |
|---|---|
| 目标 | 验证角色卡贯通完整跑团主链路 |
| 允许改的文件方向 | 只修回归发现的直接问题 |
| 后端命令 | `python -m pytest tests/server/test_character_join_import.py tests/server/test_xlsx_parser.py tests/server/test_player_runtime_state.py tests/server/test_state_service.py tests/server/test_player_features.py tests/server/test_host_room_lifecycle.py tests/server/test_rooms.py -q` |
| 前端命令 | `cd src/client && npm run build` |
| 禁止事项 | 不在回归批次扩大范围做新功能 |

手动验收链路：

1. Host 创建房间并选择剧本。
2. 玩家使用预设卡或 XLSX 加入。
3. 玩家查看角色页并 ready。
4. Host 开局。
5. 玩家提交技能检定。
6. Engine/Rule/State 完成裁决和状态变化。
7. Host HUD 与玩家角色页看到一致的当前 HP/SAN/MP/Luck。
8. 日志可查到角色加入、ready、行动、状态 patch。
