# 朋友项目功能迁移与玩家技能页统一风格计划

## Summary
- 以当前 `CodeX-aikeeper` 为主线，`G:\hermes-agent-workplace\AIkpprojects` 只作为功能来源，不能覆盖式同步。
- 先修当前截图问题：玩家技能页改成 Bauhaus 终端风格，点技能后显示说明、门槛和检定入口。
- 再分批迁移朋友项目的账号、COC7e 车卡器、剧本主角模板、剧本导入/选择和 Agent 辅助逻辑。
- 不迁移 `node_modules`、`dist`、`.env`、日志、数据库文件、PDF、`__pycache__` 等生成或本地数据。

## Key Changes
- 新增本地 COC7e 技能词典：分类、基础值、别名、短说明；技能描述 v1 不走 RAG。
- 重做 `PlayerCharacter`：使用现有 `styles.css` Bauhaus 类，按分类展示非零技能，零值技能放入“显示全部”，点开后显示详情面板。
- 技能详情里的“发起检定”默认提交 `/api/player/intent`，`intent_type=skill_check`，进入 Host/AI 裁决链；保留旧 `/api/player/skill-check` 作为测试和兜底 API。
- 迁移朋友项目 CharSheet 组件思路，但重写为我们风格：属性掷骰、职业/兴趣技能分配、背景、预览确认。
- 扩展加入页：继续支持“上传 xlsx / 本地预设”，新增“现场车卡”；最终都走同一预览确认和入房流程。
- 可选账号系统：不强制登录；登录后角色可绑定账号并查询历史角色。密码存储改用加盐 PBKDF2，不照搬朋友项目的裸 SHA256。
- 数据库以 `db_adapter.PgDatabase` 为唯一入口，补 `accounts`、`character_templates`，以及 `characters` 的 `account_id / attributes / derived_stats / occupation / background / age / gender / backstory / portrait_url / template_id`。
- 迁移剧本主角模板：PDF/文本导入结构化时保存 `protagonist_templates`，玩家创建角色时可选择剧本推荐角色。
- 朋友项目的 Agent/GameLoop 逻辑后置迁移，接入时不替换现有 PRD-29/30 `ResolutionPipeline`，只作为可开关增强路径。

## API / Types
- 新增/扩展类型：`SkillMeta`、`CharacterAttributes`、`DerivedStats`、`BackgroundData`、`Account`。
- `POST /api/player/rooms/{room_id}/join-with-character` 支持三选一：`file`、`preset_id`、`character_json`；仍要求 `player_name`。
- 新增账号 API：`POST /api/auth/register`、`POST /api/auth/login`、`GET /api/auth/me`、`GET /api/auth/me/characters`。
- 新增/补齐剧本 API：`GET /api/scenarios`、`GET /api/scenarios/{id}`、`GET /api/scenarios/{id}/preview`、`POST /api/scenarios/import-text`。
- 新增/补齐 `GET /api/player/scenarios/{scenario_id}/default-characters`，读取 `character_templates`。

## Test Plan
- 后端：跑现有 PostgreSQL/pgvector 测试入口，覆盖 xlsx/preset 不回归。
- 新增测试：技能意图提交、现场车卡 join、可选账号绑定、账号密码 hash、剧本模板保存与读取、默认角色为空场景。
- 前端：`src/client` 下 `npm run build` 必须通过。
- 手动验收：`/player/:roomId` 技能页风格一致；点技能显示说明和门槛；提交检定进入等待结算；加入页三种角色来源都能进入玩家终端。
- 回归验收：Host 舞台、玩家行动、背包/线索、预设角色锁定、RAG 测试页不被朋友项目旧代码覆盖。

## Assumptions
- 朋友项目全量迁移按“分批 cherry-pick/改写”执行，不做目录覆盖。
- 当前主线的 Bauhaus 前端、预设角色、PRD-29/30 裁决管线优先级高于朋友项目旧 UI。
- 技能描述 v1 使用本地小词典；RAG 查询规则书作为后续增强。
- 账号为可选，不阻塞房间码快速加入。
