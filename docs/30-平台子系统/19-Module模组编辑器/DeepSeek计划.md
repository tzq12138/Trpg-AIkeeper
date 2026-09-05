# Module 模组编辑器 DeepSeek 计划 V2.1

## 当前阶段说明

- 本计划当前阶段为：`P0 主链路 + 模组导入、发布准入与开房实例化风险识别版`。
- 第一轮目标不是“做一个大编辑器”，而是把 `导入草稿 -> 校验 -> 发布 -> Host 开房 -> Room 实例化隔离` 这条链路做稳。
- 当前代码以 `scenario` 为真实底座，不要假设已经存在独立 Module 服务层或 `module_versions`。
- 如遇文档与代码冲突，以当前代码为准，并在回执中明确写出差异与遗留风险。

## 执行目标

先把以下能力收口成稳定主链路：

1. Admin 可导入 PDF，生成 `knowledge_graph` 和 `quality_report`；
2. Module 有独立 `importStatus` / `publishStatus` / `ModuleReadiness` 口径；
3. Host 只看到可开房模组；
4. Player 能读公开模板接口，但读不到 truth 和完整后台结构；
5. Room start 能从 confirmed map 初始化运行态；
6. 房间运行态不反写 `scenarios`、`scenario_maps`、`character_templates`。

## 执行前必须复核的代码

- `src/server/scenario/router_scenarios.py`
- `src/server/router_admin.py`
- `src/server/scenario/quality.py`
- `src/server/db_adapter.py`
- `src/server/router_rooms.py`
- `src/server/player/router_player.py`
- `src/server/ai/map_generator.py`
- `src/server/map_persistence.py`
- `src/server/rules/triggers.py`
- `src/server/engine/rule_executor.py`
- `src/client/src/pages/AdminDashboard.tsx`
- `src/client/src/pages/HostCreate.tsx`
- `src/client/src/pages/PlayerJoinPage.tsx`
- `src/client/src/pages/CharacterBuilderPage.tsx`

## 全局实现规则

1. `importStatus` 和 `publishStatus` 必须分离，不再混用。
2. Admin / Host / Player 三套 DTO 必须分开，禁止把 `scenarios` 原始记录直接返回前端。
3. `GET /api/scenarios/{scenario_id}/templates` 必须返回公开模板字段，不得返回 truth、hidden clue、secret backstory、admin notes。
4. 地图生成必须固定 `knowledge_graph.scenes` 优先，`scenario_assets.scenes` 仅兼容旧数据。
5. 结构编辑接口必须使用受控 patch，不接受整包任意 JSON 覆盖 scenario。
6. 坏触发器不能拖垮回合结算；发布前校验，运行时降级。
7. Room 运行态不得反写 `scenarios`、`scenario_maps`、`character_templates`。
8. Module 只保存 `assetId` 或受控 URL，不保存本地路径。
9. 如本轮仍未实现 `module_versions`，回执必须明确写出“mutable scenario 遗留风险”。
10. `qualityLevel.ready` 和 `publishStatus.ready` 是两个不同字段，命名相近但语义不同；实现、测试和回执里不得混写。
11. `highRisk` 的“发布 override”与“create-room confirm_quality_risk”两条路径必须在回执中说明最终对齐策略。
12. 导出必须区分 `admin_debug_export`、`module_manifest_export`、`public_share_package`，不能把 debug/raw 导出当作可分享模组包。

## 全局禁止事项

1. 禁止把完整 `knowledge_graph`、truth、隐藏线索或 Host-only 配置发给 Player。
2. 禁止让 Module 编辑接口直接修改进行中的 Room 状态。
3. 禁止让 Room 运行态反写 `scenarios`、`scenario_maps` 或 `character_templates`。
4. 禁止把文件上传安全写在 Module 内绕过 Asset。
5. 禁止在 Host/Player 前端拼接本地素材路径。
6. 禁止一次性重做 AdminDashboard 或创建大型拖拽编辑器。
7. 禁止取消现有开房鉴权、ready 检查和地图确认规则。
8. 禁止把 blocked 模组静默开放给普通 Host。

## Batch Module-0：现状盘点与测试基线

### 目标

确认当前导入、质量报告、地图、模板接口、Host 可见列表和开房链路的真实状态。

### 允许改动

- `docs/50-AI-Keeper-Platform/19-Module模组编辑器/`
- 不改业务代码

### 任务

1. 运行 `git status --short`，记录工作区状态。
2. 搜索 `scenario_assets`、`quality_report`、`character_templates`、`map/generate`、`templates`、`create-room`。
3. 确认 `/api/admin/scenarios` 是否仍默认返回大字段。
4. 确认 `/api/scenarios/available` 是否过滤 blocked。
5. 确认 map generator 当前优先读取哪个 scenes。
6. 确认前端是否请求了后端不存在的接口。
7. 跑 Module 相关测试并记录失败项。

### 验收命令

```powershell
git status --short
```

```powershell
python -m pytest tests/server/test_quality.py tests/server/test_pdf_parser.py tests/server/test_room_security.py tests/server/test_rooms.py tests/server/test_host_room_lifecycle.py -q
```

### 预期结果

形成现状清单，至少说明：

- `importStatus` 现状；
- `publishStatus` 是否缺失；
- templates 路由是否缺口；
- create-room 与 `/api/rooms` 是否分叉；
- map generator 的数据源优先级；
- Admin 列表是否暴露大字段。

## Batch Module-1：模板接口与可开房链路闭环

### 目标

先闭合 `Host 可开房 + Player 可选模板 + Room start 可初始化 confirmed map` 这条主链。

### 允许改动

- `src/server/scenario/router_scenarios.py`
- `src/server/router_rooms.py`
- `src/server/player/router_player.py`
- `tests/server/test_room_security.py`
- `tests/server/test_rooms.py`
- `tests/server/test_character_join_import.py`

### 任务

1. 补齐或统一 `GET /api/scenarios/{scenario_id}/templates`。
2. 模板接口只返回公开字段，不返回 truth、隐藏线索、私密背景。
3. `/api/scenarios/available` 只返回可开房模组，保持 host/admin 鉴权。
4. `/api/scenarios/{scenario_id}/create-room` 与 `/api/rooms` 的校验口径保持一致。
5. 确认 Room start 从 confirmed map 初始化 `room_map_state`。
6. 为 templates 缺口、player 越权、host 成功读取添加测试。

### 验收命令

```powershell
python -m pytest tests/server/test_room_security.py tests/server/test_rooms.py tests/server/test_character_join_import.py -q
```

### 禁止事项

- 不开放 Player 查看 scenario 全量结构。
- 不复制两套创建房间逻辑造成永久分叉。
- 不让未确认地图阻断“无地图模组”的基础开房，除非发布规则明确要求。

## Batch Module-2：Module DTO 与状态口径

### 目标

建立 Module 聚合 DTO，并明确 `importStatus` / `publishStatus` / `ModuleReadiness` 三套状态。

### 允许改动

- `src/server/models.py`
- `src/server/db_adapter.py`
- `src/server/scenario/router_scenarios.py`
- `src/server/router_admin.py`
- 新增 Module 相关后端测试

### 任务

1. 定义 `ModuleListItemDTO`、`AdminModuleDetailDTO`、`ModuleHostOptionDTO`、`PlayerModulePreviewDTO`。
2. 在不破坏旧数据的前提下，引入 `publishStatus` 字段或兼容计算字段。
3. Admin scenario 列表改为轻量 DTO，避免默认返回 `raw_text`、完整 truth 等大字段。
4. Host 可用列表只返回最小开房字段。
5. Module 详情接口聚合 KG 摘要、质量、地图、素材和模板状态。
6. 为旧 scenario 缺少 `publishStatus` 的情况提供兼容策略。

### 验收命令

```powershell
python -m pytest tests/server/test_quality.py tests/server/test_room_security.py tests/server/test_rooms.py -q
```

### 禁止事项

- 不一次性迁移或删除历史 `scenarios` 字段。
- 不把 `raw_text` 和 truth 放进 Host/Player DTO。
- 不让前端继续依赖 DB 原始字段。

## Batch Module-3：发布前质量准入

### 目标

让质量报告从“提示信息”升级为“发布与可开房准入依据”。

### 允许改动

- `src/server/scenario/quality.py`
- `src/server/router_admin.py`
- `src/server/scenario/router_scenarios.py`
- `src/server/router_rooms.py`
- `tests/server/test_quality.py`
- `tests/server/test_room_security.py`
- `tests/server/test_rooms.py`

### 任务

1. 固化 `ready / warning / highRisk / blocked` 的发布矩阵。
2. blocked 模组不允许发布，也不进入普通 Host 可用列表。
3. highRisk 仅允许 Admin override，且必须提交 `reason`。
4. 发布、撤回、强制发布必须记录 `actor + reason + qualitySnapshot`。
5. 保存 KG、地图、素材或模板后，重新计算质量报告或标记 stale。
6. 中文文案可读，但测试断言不依赖文案本身。
7. 明确 `highRisk` 在发布链路和 create-room 链路上的对齐策略，并写入回执。

### 验收命令

```powershell
python -m pytest tests/server/test_quality.py tests/server/test_room_security.py tests/server/test_rooms.py -q
```

### 禁止事项

- 不用前端隐藏按钮代替后端发布校验。
- 不让 blocked 模组静默开房。
- 不让质量文案乱码进入用户界面。

## Batch Module-4：结构编辑 API 初版

### 目标

先补后端结构编辑能力，为后续 Admin UI 和可视化编辑器打基础。

### 允许改动

- `src/server/router_admin.py`
- `src/server/scenario/quality.py`
- `src/server/rules/triggers.py`
- `src/server/models.py`
- 新增 Module 编辑相关测试

### 任务

1. 提供编辑标题、公开简介、推荐人数、标签的 patch 接口。
2. 提供编辑 `scenes`、`npcs`、`clues`、`endings` 的受控 section patch。
3. truth / spoiler boundary 仅允许 Admin 或后续 Author。
4. 保存前验证 JSON 结构和关键字段，不接受整包任意覆盖。
5. 保存后重算质量报告或标记 stale。
6. 记录编辑 actor 和字段摘要。

### 验收命令

```powershell
python -m pytest tests/server/test_quality.py tests/server/test_room_security.py -q
```

### 禁止事项

- 不让编辑接口接收整包未校验 JSON 覆盖整个 scenario。
- 不允许 Host 或 Player 编辑模板。
- 不把编辑操作同步到 active room。

## Batch Module-5：角色模板、素材绑定与触发器校验

### 目标

补齐最影响开局体验的三类内容：预设调查员、素材引用、机制触发器。

### 允许改动

- `src/server/router_admin.py`
- `src/server/player/router_player.py`
- `src/server/rules/triggers.py`
- `src/server/engine/rule_executor.py`
- `src/server/map_persistence.py`
- `tests/server/test_character_join_import.py`
- `tests/server/test_rule_executor.py`
- `tests/server/test_rules.py`

### 任务

1. 增加 Admin 角色模板 CRUD，写入 `character_templates`。
2. 玩家模板读取接口返回统一公开字段。
3. 模组素材引用使用 `assetId` 或受控 URL，不保存本地路径。
4. 场景、线索、NPC、地图节点可引用素材。
5. 触发器保存前校验 `condition` 和 `mechanics`，补 `validationStatus`。
6. RuleExecutor 消费触发器时对异常结构降级，不让坏模组拖垮主链路。

### 验收命令

```powershell
python -m pytest tests/server/test_character_join_import.py tests/server/test_rule_executor.py tests/server/test_rules.py tests/server/test_room_security.py -q
```

### 禁止事项

- 不把玩家上传角色卡写回模板。
- 不把素材本地路径暴露给前端。
- 不让坏触发器直接抛异常中断整个回合结算。

## Batch Module-6：Admin UI 初版整理

### 目标

在不重做大型编辑器的前提下，让 Admin 能完成导入、查看质量、发布、生成地图、管理素材和模板。

### 允许改动

- `src/client/src/pages/AdminDashboard.tsx`
- 必要时新增轻量组件
- `src/client/src/shared/` 中已有 API helper
- 相关后端 DTO 调整

### 任务

1. 修复 Admin 剧本与素材面板中文文案。
2. 列表展示 `importStatus`、`publishStatus`、`qualityLevel`、`mapStatus`。
3. 详情区域展示质量问题、实体数量、素材数量、模板数量。
4. 增加发布、撤回、生成地图、确认地图入口。
5. 增加角色模板只读或基础编辑入口。
6. 所有失败请求显示可读错误。
7. 保持现有页面风格，不做视觉大改。

### 验收命令

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不引入大型状态管理或拖拽库。
- 不把占位 tab 包装成完整编辑器。
- 不在前端绕过后端发布和权限判断。

## Batch Module-7：版本、导出与审计方向

### 目标

为后续长团稳定性和模组分发预留版本与审计口径，但第一轮只做最小支撑。

### 允许改动

- `src/server/db_adapter.py`
- `src/server/router_admin.py`
- `src/server/export.py`
- `src/server/events/event_log.py`
- 新增版本/审计相关测试

### 任务

1. 设计 `module_versions` 或兼容快照字段。
2. 发布时可生成快照，但不强制迁移所有房间。
3. 新房间优先绑定发布快照，旧房间继续兼容 `scenarioId`。
4. 导出模组 manifest 时不包含 token、本地路径、hidden assets。
5. 记录发布、撤回、强制发布、编辑、导出事件。
6. 明确区分 `admin_debug_export`、`module_manifest_export`、`public_share_package` 三类导出 scope。

### 验收命令

```powershell
python -m pytest tests/server/test_archive.py tests/server/test_event_log.py tests/server/test_room_security.py -q
```

### 禁止事项

- 不破坏旧房间读取 scenario 的能力。
- 不把 full debug export 当作可分享模组包。
- 不把隐藏素材文件直接打进 public 包。

## Batch Module-8：端到端回归验收

### 目标

验证模组从导入到开房再到核心跑团链路的闭环。

### 手动验收流程

1. Admin 登录。
2. Admin 导入 PDF。
3. Admin 查看质量报告和结构摘要。
4. Admin 上传素材并生成地图草稿。
5. Admin 编辑地图并确认。
6. Admin 配置至少一个公开角色模板。
7. Admin 发布模组。
8. Host 登录并从可用列表选择该模组创建房间。
9. Player 加入，能看到公开模板和公开简介。
10. Host 开局后，confirmed map 初始化到运行态。
11. 玩家提交行动，AI/规则裁决读取模组结构，但不泄露 truth。
12. 房间运行态变化不反写 Module 模板。

### 回归命令

```powershell
python -m pytest tests/server/test_quality.py tests/server/test_pdf_parser.py tests/server/test_room_security.py tests/server/test_rooms.py tests/server/test_host_room_lifecycle.py tests/server/test_character_join_import.py tests/server/test_rule_executor.py tests/server/test_rules.py -q
```

```powershell
cd src/client
npm run build
npm run test
```

### 预期结果

- Admin 能完成导入、校验、地图确认、模板配置和发布；
- Host 只能选择可运行模组；
- Player 不能读取模组真相和后台结构；
- Room 运行态与 Module 模板隔离；
- 前端构建通过，中文可读。
