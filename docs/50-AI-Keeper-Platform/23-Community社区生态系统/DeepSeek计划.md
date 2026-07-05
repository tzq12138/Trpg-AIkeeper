# Community 社区生态系统 DeepSeek 计划 V2.0

## 执行原则

Community 是平台生态层，不进入当前 AI 核心链路。DeepSeek 不得先做页面热闹感，也不得直接把现有 `scenarios`、`events`、`export` 打开为公开市场。执行顺序必须是：现状复核、发布安全、审核治理、数据模型、最小受控发布、互动能力。

每个 Batch 开始前先执行 `git status --short`，确认工作区已有改动，不覆盖无关文件。涉及公开内容、审核、举报、下架和用户隐私时，必须先写测试，再实现。

## 现状依据

- 账号身份：`src/server/router_auth.py`
- Admin 后台：`src/server/router_admin.py`
- 剧本导入和质量报告：`src/server/scenario/router_scenarios.py`、`src/server/scenario/quality.py`
- 素材管理：`src/server/router_admin.py`、`src/server/db_adapter.py`
- 归档与导出：`src/server/router_archive.py`、`src/server/player/router_player_archive.py`、`src/server/export.py`
- EventLog：`src/server/events/event_log.py`
- 反剧透：`src/server/engine/spoiler_guard.py`
- 前端路由：`src/client/src/App.tsx`、`src/client/src/navigation.ts`
- 后台 UI：`src/client/src/pages/AdminDashboard.tsx`
- 当前测试：`tests/server/test_auth.py`、`tests/server/test_admin_auth.py`、`tests/server/test_archive.py`、`tests/server/test_spoiler_guard.py`

## Batch Community-0：现状复核与无实现确认

目标：

- 确认当前没有 `/api/community` 路由、community 数据表、评论、收藏、评分、举报、公开主页和社区页面。
- 盘点可复用基础：账号、Admin、剧本导入、素材、质量报告、SpoilerGuard、replay/export。
- 把 public export/public events 当前过滤偏粗的问题记录到 Safety 前置条件。

允许文件方向：

- `docs/50-AI-Keeper-Platform/23-Community社区生态系统/`
- 只读检查 `src/server/`、`src/client/src/`、`tests/server/`

建议命令：

```bash
rg -n "community|comment|favorite|rating|report|moderation|published_modules|public_profiles" src tests --glob "!src/client/node_modules/**" --glob "!src/client/dist/**"
rg -n "APIRouter\\(|@router\\.(get|post|patch|delete)" src/server
python -m pytest tests/server/test_auth.py tests/server/test_admin_auth.py tests/server/test_archive.py -q
```

验收：

- DeepSeek 输出现状报告，明确 Community 尚未实现。
- 报告列出可复用基础和不可直接公开的数据。
- 不产生源码改动。

禁止事项：

- 不新增社区路由、页面、表和迁移。
- 不把 `/api/admin/scenarios` 当公开市场。
- 不把 `/api/rooms/{room_id}/export` 直接当公开战报分享。

## Batch Community-1：发布安全和 visibility 前置

目标：

- 定义公开模组、公开战报、公开招募、用户主页的字段白名单。
- 为 public export、public replay、public events 补失败测试，证明 host-only、player-only、token、本地路径、hidden truth 不得公开。
- 对齐 Safety 的统一 visibility helper 任务，Community 不重复实现过滤规则。

允许文件方向：

- `docs/50-AI-Keeper-Platform/21-Safety跑团安全边界系统/`
- `docs/50-AI-Keeper-Platform/23-Community社区生态系统/`
- `tests/server/test_archive.py`
- 可新增 `tests/server/test_community_public_safety.py`
- 如 Safety 已启动，可涉及 `src/server/export.py`、`src/server/events/event_log.py`

建议命令：

```bash
python -m pytest tests/server/test_archive.py tests/server/test_community_public_safety.py -q
python -m pytest tests/server/test_spoiler_guard.py -q
```

验收：

- 有测试证明 public export 不含 owner token、player token、host-only、player-only、hidden truth。
- 有测试证明 public replay 只允许白名单事件类型。
- 文档明确 Community 依赖 Safety 的统一过滤。

禁止事项：

- 不用 `audience != "player"` 作为社区公开判断。
- 不把 filtering 写在前端。
- 不让 AI 输出绕过 SpoilerGuard 进入公开发布。

## Batch Community-2：审核和举报模型设计

目标：

- 设计发布状态、举报状态、审核工单状态。
- 定义下架、恢复、拒绝、申诉、封禁的权限和审计。
- 明确 Moderator 是未来角色；当前实现可先由 admin 处理。

允许文件方向：

- `docs/50-AI-Keeper-Platform/23-Community社区生态系统/`
- `docs/50-AI-Keeper-Platform/24-Plugin-Admin-Ops开放API与后台运维/`
- 可新增 `docs/30-DeepSeek任务包/Batch-Community-审核治理设计.md`

建议命令：

```bash
rg -n "Report|Moderation|hidden|removed|published|reviewing|rejected" docs/50-AI-Keeper-Platform/23-Community社区生态系统
```

验收：

- 每类公开内容都有状态机。
- 管理员操作有审计字段。
- 举报人身份不公开，作者能看到处理结果摘要。

禁止事项：

- 不实现后台 UI。
- 不新增 moderator 角色到代码。
- 不引入自动封禁逻辑。

## Batch Community-3：社区数据模型草案

目标：

- 设计 `public_profiles`、`published_modules`、`module_versions`、`community_posts`、`public_battle_reports`、`comments`、`ratings`、`favorites`、`reports`、`moderation_cases`、`community_audits`。
- 明确这些表不直接复制私密房间数据和 raw scenario 真相。
- 设计唯一约束、索引、外键方向和删除策略。

允许文件方向：

- `docs/50-AI-Keeper-Platform/23-Community社区生态系统/`
- 可新增 migration 设计文档，但不执行迁移

建议命令：

```bash
rg -n "raw_text|knowledge_graph|owner_token|player_token|original_file_path" docs/50-AI-Keeper-Platform/23-Community社区生态系统
```

验收：

- 数据模型区分公开对象、源对象、审核对象和互动对象。
- 所有公开对象都有 `status`、`visibility`、`author_account_id` 或等价归属。
- 评论、评分、收藏、举报都有账号归属和限速测试计划。

禁止事项：

- 不修改 `src/server/db_adapter.py`。
- 不新增真实迁移。
- 不把 `scenarios.raw_text` 复制到公开表。

## Batch Community-4：公开用户主页最小实现

启动条件：

- User 权限文档稳定。
- Safety 的公开字段口径稳定。
- 用户确认开始社区工程实现。

目标：

- 新增公开主页最小数据模型和接口。
- 用户可编辑自己的公开显示名、简介和可见性。
- Visitor 可读取公开主页。
- 私密角色、私密房间、token、账号内部字段不出现在公开主页。

允许文件方向：

- 可新增 `src/server/community/`
- `src/server/main.py`
- `src/server/db_adapter.py` 或项目实际迁移位置
- `src/client/src/navigation.ts`
- 可新增 `src/client/src/pages/PublicProfilePage.tsx`
- 可新增 `tests/server/test_community_profiles.py`

建议命令：

```bash
python -m pytest tests/server/test_community_profiles.py tests/server/test_auth.py tests/server/test_admin_auth.py -q
cd src/client && npm run build
```

验收：

- 未登录 visitor 可看公开 profile。
- 用户只能修改自己的 profile。
- 默认 profile 不公开私密房间和角色。
- Admin 能隐藏违规 profile 并留下审计。

禁止事项：

- 不实现关注和私信。
- 不展示玩家角色详情。
- 不展示用户登录凭证或内部 username 以外敏感资料。

## Batch Community-5：模组发布最小实现

启动条件：

- Module 已有公开版本草稿和私密源数据分离设计。
- Safety 已有发布前脱敏测试。
- Admin/Ops 审核模型已确认。

目标：

- 作者从已有 scenario 或 Module 草稿创建 `published_module` 草稿。
- 生成 `module_version` 的公开 payload。
- 提交审核后由 admin 通过或拒绝。
- 通过后出现在公开模组列表。

允许文件方向：

- `src/server/community/`
- `src/server/scenario/router_scenarios.py`
- `src/server/router_admin.py`
- `src/client/src/pages/AdminDashboard.tsx`
- 可新增 `src/client/src/pages/CommunityModulesPage.tsx`
- 可新增 `tests/server/test_community_modules.py`

建议命令：

```bash
python -m pytest tests/server/test_community_modules.py tests/server/test_spoiler_guard.py tests/server/test_admin_auth.py -q
cd src/client && npm run build
```

验收：

- 未审核模组不出现在公开列表。
- 公开模组不含 raw_text、truth、hidden clue、hidden NPC、original_file_path、token。
- Admin 可通过、拒绝、隐藏和恢复。
- 作者只能管理自己的发布草稿。

禁止事项：

- 不开放付费。
- 不公开原始 PDF。
- 不绕过 Module 的版本草稿。

## Batch Community-6：评论、收藏、评分

目标：

- 给已发布模组和公开战报增加收藏、评论、评分。
- 评论支持作者删除自己内容、管理员隐藏违规内容。
- 评分限制同一账号同一目标一条记录。
- 增加基础限速和测试。

允许文件方向：

- `src/server/community/`
- `src/client/src/pages/CommunityModulesPage.tsx`
- 可新增 `tests/server/test_community_interactions.py`

建议命令：

```bash
python -m pytest tests/server/test_community_interactions.py tests/server/test_community_modules.py -q
cd src/client && npm run build
```

验收：

- 未登录用户不能评论和评分。
- 用户可删除自己的评论。
- Admin 可隐藏任何违规评论。
- 重复评分会更新而不是刷多条。
- 收藏默认私人，不进公开主页除非用户显式公开。

禁止事项：

- 不做推荐算法。
- 不做关注和私信。
- 不把评论写入跑团房间事件流。

## Batch Community-7：举报和审核后台

目标：

- 实现举报提交、审核工单、管理员处理、下架或驳回。
- AdminDashboard 增加社区审核 tab。
- 所有处理写 `community_audits`。

允许文件方向：

- `src/server/community/`
- `src/server/router_admin.py`
- `src/client/src/pages/AdminDashboard.tsx`
- 可新增 `tests/server/test_community_moderation.py`

建议命令：

```bash
python -m pytest tests/server/test_community_moderation.py tests/server/test_admin_auth.py -q
cd src/client && npm run build
```

验收：

- 登录用户可举报公开内容。
- 举报人身份不展示给被举报内容作者。
- Admin 可处理举报并隐藏或恢复内容。
- 审核操作有审计记录。

禁止事项：

- 不自动封禁账号。
- 不公开举报详情。
- 不删除底层源数据，只改变公开状态。

## Batch Community-8：公开招募和战报分享

目标：

- Community 只提供公开发现入口。
- 招募详情和报名流程仍走 Schedule。
- 战报分享必须从 Journal/export 生成脱敏 payload 并由 owner 或成员显式发布。

允许文件方向：

- `src/server/community/`
- `src/server/player/router_player_archive.py`
- `src/server/export.py`
- `src/client/src/pages/CommunityRecruitPage.tsx`
- `src/client/src/pages/PublicBattleReportPage.tsx`
- 可新增 `tests/server/test_community_recruit_and_reports.py`

建议命令：

```bash
python -m pytest tests/server/test_community_recruit_and_reports.py tests/server/test_archive.py tests/server/test_room_security.py -q
cd src/client && npm run build
```

验收：

- 公开招募只展示 Schedule 允许字段。
- 报名不会绕过 Schedule 审批。
- 战报分享不含 host-only、player-only、token、hidden truth。
- 房间成员不同意公开的角色信息不展示。

禁止事项：

- 不把私密房间直接列入社区。
- 不让社区报名直接创建 player token。
- 不用当前 public export 原样生成公开战报。

## Batch Community-9：回归验收

目标：

- 确保社区能力不破坏核心跑团主链路。
- 确保公开内容安全、审核、举报、权限、前端 build 都通过。

建议命令：

```bash
python -m pytest tests/server/test_auth.py tests/server/test_admin_auth.py tests/server/test_archive.py tests/server/test_room_security.py -q
python -m pytest tests/server/test_community_profiles.py tests/server/test_community_modules.py tests/server/test_community_interactions.py tests/server/test_community_moderation.py -q
cd src/client && npm run build
cd src/client && npm run test
```

手动验收：

1. Visitor 浏览公开模组列表。
2. Author 创建模组草稿并提交审核。
3. Admin 通过审核后模组公开。
4. Player 收藏、评论、评分。
5. Player 举报违规评论。
6. Admin 隐藏评论并留下审计。
7. Host 从公开模组创建房间，核心跑团链路仍可完成。
8. Owner 创建公开战报分享，检查不含 token 和剧透。

禁止事项：

- 不跳过 Safety 检查。
- 不用页面隐藏代替后端权限。
- 不在未审核时公开任何用户生成内容。
