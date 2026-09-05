# Community 社区生态系统 DeepSeek 计划 V2.1

## 当前阶段说明

- 本计划当前阶段为：`P0 边界设计 + 公开发布安全、审核治理与数据模型风险识别版`。
- 当前仓库没有 Community 子系统，没有 `/api/community`、社区表、社区页面、评论、收藏、评分、举报和公开主页。
- 第一轮目标不是做“一个社区页面”，而是把公开对象、脱敏版本、审核状态、举报留痕、成员同意和工程启动门槛写成稳定工程口径。
- `Community-0` 到 `Community-3` 可作为现状复核、发布安全、审核治理、数据模型草案批次；`Community-4+` 必须在用户再次确认后再进入工程实现。

## 执行原则

Community 是平台生态层，不进入当前 AI 核心链路。DeepSeek 不得先做页面热闹感，也不得直接把现有 `scenarios`、`events`、`export`、`campaign archive` 打开成公开市场。

所有工程批次开始前先执行 `git status --short`，确认工作区已有改动，不覆盖无关文件。涉及公开内容、审核、举报、下架、隐私和授权素材时，必须优先写测试或补文档契约，再谈实现。

## 现状依据

- 账号与权限：`src/server/router_auth.py`
- 管理后台：`src/server/router_admin.py`
- 剧本导入与质量报告：`src/server/scenario/router_scenarios.py`
- 事件可见性：`src/server/events/event_log.py`
- 导出：`src/server/export.py`
- 归档与 replay：`src/server/router_archive.py`、`src/server/player/router_player_archive.py`
- 反剧透：`src/server/engine/spoiler_guard.py`
- 前端路由：`src/client/src/navigation.ts`、`src/client/src/App.tsx`
- 后台 UI：`src/client/src/pages/AdminDashboard.tsx`
- 当前测试：`tests/server/test_auth.py`、`tests/server/test_admin_auth.py`、`tests/server/test_archive.py`、`tests/server/test_spoiler_guard.py`

## 全局实现规则

1. Community 不是当前核心跑团链路依赖，不抢 Room、AI、Transaction、State、Projection、Journal 的实现优先级。
2. 未经用户再次确认，不进入 `/api/community`、社区表、社区页面的真实实现。
3. `PublishedModule` 公开响应只能使用 `public_payload` 或等价脱敏快照，不得直接返回源 `scenario`。
4. `PublicBattleReport` 只能使用 Safety `public_export` 口径或等价安全构建流程，不得直接公开 raw export、raw replay、raw events。
5. `PublicProfile` 默认最小公开：不公开私密房间、角色详情、收藏、出勤、举报和审核记录。
6. `Comment` / `Rating` / `Favorite` 属于 Community 互动对象，不写入房间事件流，不改写世界状态。
7. `Report`、`ModerationCase`、`CommunityAudit` 必须分层；举报人身份不对外公开，内部备注不进公开页。
8. Moderator 是未来角色；当前阶段如果进入实现，先按 `admin-only` 处理，不新增 moderator 代码角色。
9. AI 只能辅助摘要、标签和风险提示，不得自动发布、自动下架、自动封禁、自动通过举报。
10. 未授权素材不得进入任何公开 payload；公开页面不得暴露本地路径、`storageKey`、原始 PDF。
11. `Community-4+` 启动前必须确认 `21-Safety`、`19-Module`、`22-Schedule`、`24-Admin/Ops` 的前置口径已通过。
12. `Community-1` 如果补 public safety 测试，只允许验证和消费 Safety helper，不允许在 Community 内复制或改写一套 visibility 规则。
13. 本轮“文档阶段通过”只放行 `Community-0` 到 `Community-3`；`Community-4+` 仍然不是默认批准状态。

## Batch Community-0：现状复核与无实现确认

### 目标

- 确认当前没有 `/api/community` 路由、community 数据表、评论、收藏、评分、举报、公开主页和社区页面。
- 盘点可复用基础：账号、Admin、剧本导入、素材、质量报告、SpoilerGuard、replay/export。
- 记录当前哪些能力“可作为 Community 原材料”，哪些能力“绝不能直接公开”。

### 允许文件方向

- `docs/50-AI-Keeper-Platform/23-Community社区生态系统/`
- 只读检查 `src/server/`、`src/client/src/`、`tests/server/`

### 建议命令

```bash
rg -n "community|comment|favorite|rating|report|moderation|published_modules|public_profiles" src/server src/client/src tests
rg -n "APIRouter\\(|@router\\.(get|post|patch|delete)" src/server
python -m pytest tests/server/test_auth.py tests/server/test_admin_auth.py tests/server/test_archive.py -q
```

### 验收

- 现状报告明确 Community 尚未实现。
- 现状报告列出可复用基础：账号、Admin、Module、Asset、Journal/export、SpoilerGuard。
- 现状报告列出不可直接公开的数据：`raw_text`、truth、ending、raw events、token、原始路径。
- 不产生源码改动。

### 禁止事项

- 不新增社区路由、页面、表和迁移。
- 不把 `/api/admin/scenarios` 当公开市场。
- 不把 `/api/rooms/{room_id}/export` 直接当公开战报分享。

## Batch Community-1：发布安全与公开 DTO 前置

### 目标

- 定义 `PublishedModule`、`PublicBattleReport`、`PublicRecruitPost`、`PublicProfile` 的字段白名单和禁止字段。
- 明确 `PublishedModule` 与源 `scenario`、`PublicBattleReport` 与 raw export 的边界。
- 为 public export / replay / events 补失败测试或至少补测试计划，证明它们不能被直接社区化。

### 允许文件方向

- `docs/50-AI-Keeper-Platform/21-Safety跑团安全边界系统/`
- `docs/50-AI-Keeper-Platform/23-Community社区生态系统/`
- `tests/server/test_archive.py`
- 可新增 `tests/server/test_community_public_safety.py`
- 如用户明确要求工程验证，可涉及 `src/server/export.py`、`src/server/events/event_log.py`

### 建议命令

```bash
python -m pytest tests/server/test_archive.py tests/server/test_spoiler_guard.py -q
python -m pytest tests/server/test_community_public_safety.py -q
```

### 验收

- 文档明确 `PublishedModule` 只用 `public_payload`。
- 文档明确 `PublicBattleReport` 只来自 Safety `public_export` 或等价安全构建流程。
- 如进入工程验证，有测试证明公开输出不含 host-only、player-only、token、本地路径、truth、hidden clue。
- 文档明确 Community 不自建 visibility helper，只复用 Safety 口径。
- 工程回执明确说明 Community 只消费 Safety helper，而没有在 Community 内复制一套过滤逻辑。

### 禁止事项

- 不用 `audience != "player"` 作为 Community 公开判断。
- 不把 filtering 写在前端。
- 不让 AI 输出绕过 SpoilerGuard 进入公开发布。

## Batch Community-2：审核、举报和状态机模型设计

### 目标

- 设计公开对象状态机、评论状态机、举报状态机、审核工单状态机。
- 定义下架、恢复、驳回、申诉、删除、警告的权限边界和审计字段。
- 明确 Moderator 是未来角色；当前可先按 `admin-only` 模型设计。

### 允许文件方向

- `docs/50-AI-Keeper-Platform/23-Community社区生态系统/`
- `docs/50-AI-Keeper-Platform/24-Plugin-Admin-Ops开放API与后台运维/`
- 可新增 `docs/30-DeepSeek任务包/Batch-Community-审核治理设计.md`

### 建议命令

```bash
rg -n "Report|Moderation|hidden|removed|published|reviewing|rejected|archived" docs/50-AI-Keeper-Platform/23-Community社区生态系统
```

### 验收

- 每类公开对象有稳定状态机。
- `Report`、`ModerationCase`、`CommunityAudit` 分层明确。
- 举报人身份不公开，作者可看到处理结果摘要。
- Admin 操作必须进入 `CommunityAudit`。

### 禁止事项

- 不实现后台 UI。
- 不新增 moderator 角色到代码。
- 不引入自动封禁逻辑。

## Batch Community-3：社区数据模型草案

### 目标

- 设计 `public_profiles`、`published_modules`、`module_versions`、`module_asset_licenses`、`community_posts`、`public_battle_reports`、`comments`、`ratings`、`favorites`、`reports`、`moderation_cases`、`community_audits`。
- 明确公开对象、源对象、审核对象和互动对象的分层，不把源 `scenario` 和私密房间数据直接复制到公开表。
- 设计唯一约束、索引、外键方向、删除策略和限速测试计划。

### 允许文件方向

- `docs/50-AI-Keeper-Platform/23-Community社区生态系统/`
- 可新增 migration 设计文档，但不执行迁移

### 建议命令

```bash
rg -n "raw_text|truth|ending|owner_token|player_token|original_file_path|storageKey" docs/50-AI-Keeper-Platform/23-Community社区生态系统
```

### 验收

- 数据模型区分公开对象、源对象、审核对象和互动对象。
- 所有公开对象都有 `status`、`visibility`、`author_account_id` 或等价归属。
- 评论、评分、收藏、举报都有账号归属和反滥用测试计划。
- 授权素材字段完整：`assetId`、`licenseType`、`publicUseAllowed`、`attribution?`、`source?`、`reviewerChecked?`。

### 禁止事项

- 不修改 `src/server/db_adapter.py`。
- 不新增真实迁移。
- 不把 `scenarios.raw_text` 复制到公开表。

## Batch Community-4：公开用户主页最小实现

### 启动条件

- 用户明确确认开始 Community 工程实现。
- `21-Safety` 的公开字段与 visibility 口径稳定。
- `02-User` 权限文档和账号恢复边界稳定。

### 目标

- 新增公开主页最小数据模型和接口。
- 用户可编辑自己的公开显示名、简介和可见性。
- Visitor 可读取公开主页。
- 私密房间、角色详情、收藏、举报、审核记录默认不公开。

### 允许文件方向

- 可新增 `src/server/community/`
- `src/server/main.py`
- `src/server/db_adapter.py` 或项目实际迁移位置
- `src/client/src/navigation.ts`
- `src/client/src/App.tsx`
- 可新增 `src/client/src/pages/PublicProfilePage.tsx`
- 可新增 `tests/server/test_community_profiles.py`

### 建议命令

```bash
python -m pytest tests/server/test_community_profiles.py tests/server/test_auth.py tests/server/test_admin_auth.py -q
cd src/client && npm run build
```

### 验收

- Visitor 可看公开 profile。
- 用户只能修改自己的 profile。
- 默认不公开私密房间、角色详情、收藏、举报和审核记录。
- Admin 能隐藏违规 profile 并写审计。
- 工程回执说明 `profileId / slug / displayName` 策略。

### 禁止事项

- 不实现关注和私信。
- 不展示用户登录凭证或内部敏感字段。
- 不把 `accounts` 原始记录直接返回给前端。

## Batch Community-5：模组发布最小实现

### 启动条件

- 用户明确确认继续做 Community 工程。
- `19-Module` 的 `public payload / module version boundary` 已通过。
- `21-Safety` 的发布前脱敏测试已通过。
- `24-Admin/Ops` 的审核模型已确认。

### 目标

- 作者从已有 `scenario` 或 Module 草稿创建 `published_module` 草稿。
- 生成 `module_version` 的公开 payload。
- 提交审核后由 admin 通过或拒绝。
- 通过后出现在公开模组列表。

### 允许文件方向

- `src/server/community/`
- `src/server/scenario/router_scenarios.py`
- `src/server/router_admin.py`
- `src/client/src/navigation.ts`
- `src/client/src/App.tsx`
- 可新增 `src/client/src/pages/CommunityModulesPage.tsx`
- 可新增 `tests/server/test_community_modules.py`

### 建议命令

```bash
python -m pytest tests/server/test_community_modules.py tests/server/test_spoiler_guard.py tests/server/test_admin_auth.py -q
cd src/client && npm run build
```

### 验收

- 未审核模组不出现在公开列表。
- 公开模组不含 `raw_text`、truth、ending、hidden clue、hidden NPC、`original_file_path`、token。
- `PublishedModule` 公开响应只使用 `public_payload`。
- Admin 可通过、拒绝、隐藏和恢复。
- 作者只能管理自己的发布草稿。
- 工程回执说明作者授权模型：`source_scenario` owner、Admin 代管、协作者、导入者与作者关系。

### 禁止事项

- 不开放付费。
- 不公开原始 PDF。
- 不绕过 Module 的版本草稿和授权素材检查。

## Batch Community-6：评论、收藏、评分

### 启动条件

- 用户明确确认继续做 Community 工程。
- `Community-5` 已通过。
- 审核与限速前置已确认。

### 目标

- 给已发布模组和公开战报增加收藏、评论、评分。
- 评论支持作者删除自己内容、管理员隐藏违规内容。
- 评分限制同一账号同一目标一条记录。
- 增加基础限速和反滥用测试。

### 允许文件方向

- `src/server/community/`
- 可新增 `src/client/src/pages/CommunityModulesPage.tsx`
- 可新增 `tests/server/test_community_interactions.py`

### 建议命令

```bash
python -m pytest tests/server/test_community_interactions.py tests/server/test_community_modules.py -q
cd src/client && npm run build
```

### 验收

- 评论要求登录。
- 评论有限速。
- 作者能删除自己评论。
- Admin 能隐藏违规评论。
- 评分同一账号同一目标唯一，重复评分为更新。
- 收藏默认私人。

### 禁止事项

- 不把评论写进房间事件流。
- 不把收藏默认公开。
- 不做推荐排序和热榜。

## Batch Community-7：举报与审核后台

### 启动条件

- 用户明确确认继续做 Community 工程。
- `24-Admin/Ops` 的 moderation / audit 能力已通过。

### 目标

- 新增举报接口、审核工单和 Admin 审核后台最小闭环。
- 支持下架、恢复、驳回举报、警告作者。
- 保证举报人身份不对外公开，内部备注不进公开页。

### 允许文件方向

- `src/server/community/`
- `src/server/router_admin.py`
- `src/client/src/pages/AdminDashboard.tsx`
- 可新增 `tests/server/test_community_moderation.py`

### 建议命令

```bash
python -m pytest tests/server/test_community_moderation.py tests/server/test_admin_auth.py -q
cd src/client && npm run build
```

### 验收

- 举报生成 `ModerationCase`。
- 举报人身份不公开给作者。
- Admin 操作进入 `CommunityAudit`。
- 下架内容公开不可见，作者能看到处理结果摘要。

### 禁止事项

- 不引入自动封禁。
- 不引入 moderator 代码角色。
- 不让 AI 自动决定工单结果。

## Batch Community-8：公开招募与公开战报

### 启动条件

- 用户明确确认继续做 Community 工程。
- `22-Schedule` 的公开招募 DTO / 报名审批边界已通过。
- `11-Journal`、`21-Safety` 的 replay / export / public_export 边界已通过。

### 目标

- 新增公开招募入口和公开战报分享入口。
- `PublicRecruitPost` 只展示 Schedule 允许的公开字段。
- `PublicBattleReport` 只展示显式发布、脱敏且符合成员同意规则的内容。

### 允许文件方向

- `src/server/community/`
- `src/server/router_archive.py`
- `src/server/export.py`
- `src/client/src/navigation.ts`
- `src/client/src/App.tsx`
- 可新增 `src/client/src/pages/CommunityRecruitPage.tsx`
- 可新增 `src/client/src/pages/PublicBattleReportPage.tsx`
- 可新增 `tests/server/test_community_public_sharing.py`

### 建议命令

```bash
python -m pytest tests/server/test_community_public_sharing.py tests/server/test_archive.py tests/server/test_spoiler_guard.py -q
cd src/client && npm run build
```

### 验收

- 招募公开入口只显示 Schedule 白名单字段。
- 社区报名不直接创建 `player_token`。
- 公开战报不含 host-only、player-only、token、hidden truth、private clue。
- 玩家角色名公开需要同意或匿名化策略。
- 工程回执说明同意粒度和撤回同意后的处理策略。

### 禁止事项

- 不把当前 `public export` 原样当 Community 公开战报。
- 不绕过 Schedule 直接报名入房。
- 不公开 campaign archive 原始对象。

## Batch Community-9：回归验收

### 目标

- 跑 Community 相关后端测试。
- 跑前端 build。
- 验证 Community 没有反向污染 Room、AI、State、Projection、Journal 主链路。

### 建议命令

```bash
python -m pytest tests/server/test_auth.py tests/server/test_admin_auth.py tests/server/test_archive.py tests/server/test_spoiler_guard.py -q
python -m pytest tests/server/test_community_public_safety.py tests/server/test_community_profiles.py tests/server/test_community_modules.py tests/server/test_community_interactions.py tests/server/test_community_moderation.py tests/server/test_community_public_sharing.py -q
cd src/client && npm run build
```

### 验收

- Community 公开内容均走 DTO 白名单。
- Community 不公开 token、`raw_text`、truth、hidden clue、hidden NPC、原始路径。
- Community 页面与接口只在用户明确确认后的批次里实现。
- Community 不影响当前创建房间、玩家加入、ready、开局、AI 裁决主链路。
- 工程回执明确 `Community-4+` 是否仍保持 gated 状态。

### 禁止事项

- 不因为 Community 回归而顺手修改核心跑团逻辑。
- 不在未确认前额外扩展社交网络、私信、关注、推荐和付费。
