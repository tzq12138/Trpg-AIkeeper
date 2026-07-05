# Module 模组编辑器 DeepSeek 计划 V2.0

## 执行目标

先把“导入草稿 -> 校验 -> 发布 -> Host 选模组开房 -> Room 运行态隔离”这条链路稳定下来，再逐步做结构编辑和可视化编辑器。第一轮不要做大型前端重构，不要做社区市场，不要迁移全部历史数据。

执行前必须复核以下代码：

- `src/server/scenario/router_scenarios.py`
- `src/server/router_admin.py`
- `src/server/scenario/quality.py`
- `src/server/ai/ai_kp.py`
- `src/server/db_adapter.py`
- `src/server/router_rooms.py`
- `src/server/player/router_player.py`
- `src/server/ai/map_generator.py`
- `src/server/map_persistence.py`
- `src/client/src/pages/AdminDashboard.tsx`
- `src/client/src/pages/HostCreate.tsx`
- `src/client/src/pages/PlayerJoinPage.tsx`
- `src/client/src/pages/CharacterBuilderPage.tsx`

## 全局禁止事项

1. 禁止把完整 `knowledge_graph`、truth、隐藏线索或 Host-only 配置发给 Player。
2. 禁止让 Module 编辑接口直接修改进行中的 Room 状态。
3. 禁止让 Room 运行态反写 `scenarios`、`scenario_maps` 或 `character_templates`。
4. 禁止把文件上传安全写在 Module 内绕过 Asset。
5. 禁止在 Host/Player 前端拼接本地素材路径。
6. 禁止一次性重做 AdminDashboard 或创建大型拖拽编辑器。
7. 禁止取消现有开房鉴权、ready 检查和地图确认规则。
8. 禁止把 blocked 模组无提示开放给普通 Host。

## Batch Module-0：现状盘点与测试基线

### 目标

确认当前 scenario、quality、map、template、room start 和前端入口的真实状态。

### 允许改动

- `docs/50-AI-Keeper-Platform/19-Module模组编辑器/`
- 不改业务代码

### 任务

1. 运行 `git status --short`，记录工作区改动。
2. 搜索 `scenario_assets`、`quality_report`、`character_templates`、`map/generate`、`templates`、`create-room`。
3. 确认 PDF 导入、质量报告、地图确认、Host 选模组、Player 模板读取的现状。
4. 确认前端是否请求了后端不存在的接口。
5. 跑 Module 相关测试并记录失败项。

### 验收命令

```powershell
git status --short
```

```powershell
python -m pytest tests/server/test_quality.py tests/server/test_pdf_parser.py tests/server/test_room_security.py tests/server/test_rooms.py tests/server/test_host_room_lifecycle.py -q
```

### 预期结果

得到一份分层问题清单：导入、发布状态、质量准入、模板接口、地图实例化、前端文案和权限风险分别归类。

## Batch Module-1：接口缺口与可开房链路修复

### 目标

优先修复当前主链路断点，让“有质量报告和 confirmed map 的模组可被 Host 稳定开房”。

### 允许改动

- `src/server/scenario/router_scenarios.py`
- `src/server/router_rooms.py`
- `src/server/player/router_player.py`
- `tests/server/test_room_security.py`
- `tests/server/test_rooms.py`
- `tests/server/test_character_join_import.py`

### 任务

1. 补齐或统一 `GET /api/scenarios/{scenario_id}/templates`。
2. 模板接口只返回公开角色模板字段，不返回真相和隐藏结构。
3. `/api/scenarios/available` 只返回可开房模组，保留 host/admin 鉴权。
4. `/api/scenarios/{id}/create-room` 与 `/api/rooms` 创建逻辑保持一致。
5. 确认 Room start 从 confirmed map 初始化 `room_map_state`。
6. 为缺失路由、player 越权、host 成功读取添加测试。

### 验收命令

```powershell
python -m pytest tests/server/test_room_security.py tests/server/test_rooms.py tests/server/test_character_join_import.py -q
```

### 禁止事项

- 不开放 Player 查看 scenario 全量结构。
- 不让未确认地图阻断无地图模组的基本开房，除非发布规则明确要求。
- 不复制两套创建房间逻辑造成分叉。

## Batch Module-2：Module DTO 与状态口径

### 目标

建立 Module 聚合 DTO，并分离导入状态和发布状态。

### 允许改动

- `src/server/models.py`
- `src/server/db_adapter.py`
- `src/server/scenario/router_scenarios.py`
- `src/server/router_admin.py`
- `tests/server/test_quality.py`
- 新增 Module 相关后端测试

### 任务

1. 定义 Module DTO：id、title、importStatus、publishStatus、qualityLevel、counts、mapStatus、assetCount、templateCount。
2. 在不破坏旧数据的前提下增加发布状态字段或用兼容计算字段过渡。
3. Admin scenario 列表改为轻量 DTO，避免默认返回大字段。
4. Host 可用列表只返回最小字段。
5. Module 详情接口聚合 KG 摘要、质量、地图、素材和模板状态。
6. 为旧 scenario 缺少发布状态的情况提供兼容策略。

### 验收命令

```powershell
python -m pytest tests/server/test_quality.py tests/server/test_room_security.py tests/server/test_rooms.py -q
```

### 禁止事项

- 不一次性迁移或删除历史 `scenarios` 字段。
- 不把 `raw_text` 和 truth 放进 Host/Player DTO。
- 不让前端依赖 DB 原始字段。

## Batch Module-3：发布前质量准入

### 目标

让质量报告从“提示信息”升级为“发布和可开房准入依据”。

### 允许改动

- `src/server/scenario/quality.py`
- `src/server/router_admin.py`
- `src/server/scenario/router_scenarios.py`
- `src/server/router_rooms.py`
- `tests/server/test_quality.py`
- `tests/server/test_room_security.py`
- `tests/server/test_rooms.py`

### 任务

1. 明确 `ready/warning/highRisk/blocked` 的发布策略。
2. blocked 模组不允许发布，也不进入普通 Host 可用列表。
3. highRisk 可由 Admin 强制发布，但必须提交 reason。
4. 发布或强制发布记录 actor、reason 和 quality snapshot。
5. 保存 KG、地图、素材或模板变更后标记需要重新校验。
6. 补质量报告中文文案，保持测试可断言字段不依赖文案。

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

1. 提供编辑标题、简介、公开简介、推荐人数、标签的接口。
2. 提供编辑 scenes、npcs、clues、truth、endings 的接口。
3. 保存前验证 JSON 结构和关键字段。
4. 编辑 truth 和 spoiler boundaries 只允许 Admin 或后续 Author。
5. 保存后重新计算质量报告。
6. 记录编辑 actor 和字段摘要。

### 验收命令

```powershell
python -m pytest tests/server/test_quality.py tests/server/test_room_security.py -q
```

### 禁止事项

- 不让编辑接口接受任意未校验 JSON 覆盖整个 scenario。
- 不允许 Host 或 Player 编辑模板。
- 不把编辑操作同步到 active room。

## Batch Module-5：角色模板、素材绑定与触发器校验

### 目标

补齐模组中最容易影响开局体验的三类内容：预设调查员、素材引用、机制触发器。

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
2. 玩家模板读取接口返回统一字段。
3. 模组素材引用使用 asset id 或受控 URL，不保存本地路径。
4. 场景、线索、NPC、地图节点可引用素材。
5. 触发器编辑保存前校验 condition 和 mechanics。
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
2. Scenario 列表展示 importStatus、publishStatus、qualityLevel、mapStatus。
3. 详情区域展示质量报告问题、实体数量、素材数量、模板数量。
4. 增加发布、撤回、生成地图、确认地图的入口。
5. 增加角色模板只读或基础编辑入口。
6. 所有失败请求显示可读错误。
7. 保持现有 Bauhaus 风格，不做视觉大改。

### 验收命令

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不引入大型状态管理或拖拽库。
- 不把占位数据库 tab 包装成完整编辑器。
- 不在前端绕过后端发布和权限判断。

## Batch Module-7：版本、导入导出与审计方向

### 目标

为后续社区模组和长团稳定性预留版本与审计口径，但第一轮只做轻量设计或最小后端支撑。

### 允许改动

- `src/server/db_adapter.py`
- `src/server/router_admin.py`
- `src/server/export.py`
- `src/server/events/event_log.py`
- 新增版本/审计测试

### 任务

1. 设计 `module_versions` 或兼容快照字段。
2. 发布时可生成快照，但不强制迁移所有房间。
3. 新房间优先绑定发布快照，旧房间继续兼容 scenario id。
4. 导出模组 manifest 时不包含敏感 token 和本地路径。
5. 记录发布、撤回、强制发布、编辑、导出事件。

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
6. Admin 配置至少一个角色模板。
7. Admin 发布模组。
8. Host 登录并从可用列表选择该模组创建房间。
9. Player 加入，能看到预设角色模板和公开信息。
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

- Admin 能完成导入、校验、地图确认、模板配置和发布。
- Host 只能选择可运行模组。
- Player 不能读取模组真相和后台结构。
- Room 运行态与 Module 模板隔离。
- 前端构建通过，中文可读。

## 与其他模块接口

| 模块 | Module 依赖 | 对方需要遵守 |
| --- | --- | --- |
| Room | 从模组创建房间和实例化地图 | Room 不反写 Module 模板 |
| User | Admin、Host、Author、Player 权限 | 模组编辑和发布必须后端鉴权 |
| Asset | 原件、素材文件和安全 URL | Module 只保存 asset 引用 |
| WorldBook | KG 抽取和结构语义 | Module 编辑保存后可触发质量复核 |
| Clue | 线索结构和手out绑定 | 未发现线索不进入玩家视角 |
| Scene/Map | 地图草稿和 confirmed map | confirmed map 才用于开房初始化 |
| Rule | 触发器 schema 和机制 | Module 只定义触发器，不执行裁决 |
| Character | 角色模板字段和 xlsx 数据 | 玩家加入复制模板，不反写模板 |
| AI-Keeper | 结构化和建议 | AI 不直接发布或编辑模组 |
| State | 运行态事实 | State 不污染模板 |
| Projection | 可见性过滤 | Player 不看 truth 和 Host-only 字段 |
| Host Client | 选择模组、开房 | Host 不编辑模板 |
| Player Client | 读取公开信息和模板 | Player 不读后台 KG |
| Safety | 防剧透和发布准入 | blocked/highRisk 需要后端拦截或 override |
| Admin/Ops | 审计、归档和维护 | 发布、撤回、导出需记录 actor |
