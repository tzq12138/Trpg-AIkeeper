# Community 社区生态系统 PRD V2.1

## 当前阶段说明

- 本 PRD 当前阶段为：`P0 边界设计 + 公开发布安全、审核治理与数据模型风险识别版`。
- 当前仓库没有 Community 子系统，没有 `/api/community`、社区数据表、公开主页、模组市场、招募广场、评论、收藏、评分和举报工作流。
- 本轮重点不是实现社区产品，而是定义公开对象、脱敏版本、审核状态、举报留痕、成员同意、资料隐私和工程启动门槛。
- `Community-0` 到 `Community-3` 可作为文档、测试和数据模型前置批次；`Community-4` 之后的所有工程实现都必须在用户再次确认后再启动。
- 文档通过不代表可以直接公开 `scenarios`、`events`、`public export`、`campaign archive` 或现有后台接口。

## 背景

AI-Keeper 想成长为平台，最终一定需要 Community：玩家发现公开内容，Host 发现模组，作者发布作品，房间成员分享战报，管理员处理违规和举报。

但 Community 也是整个平台里风险最高的层之一，因为它同时碰到：

- 剧透与真相泄露；
- 版权与素材授权；
- 用户隐私；
- 骚扰、刷分、垃圾评论；
- 举报、下架、恢复、申诉和审计；
- “源数据”和“公开版本”混层。

当前仓库里已经有可复用基础，但都还不是 Community：

- `router_auth.py` 提供账号体系；
- `router_admin.py` 提供后台基础；
- `router_scenarios.py` 提供剧本导入和质量报告；
- `event_log.py`、`router_archive.py`、`export.py` 提供 replay / export / public events 基础；
- `spoiler_guard.py` 提供反剧透审查。

这些能力只能作为 Community 的底座，不能被误读成“社区市场已经有一半，只差页面”。

## 目标

1. 明确 Community 的产品范围，以及它不进入当前核心跑团链路的边界。
2. 定义公开内容的发布前置条件、脱敏规则、审核状态、下架恢复和治理审计。
3. 区分 `PublicProfile`、`PublishedModule`、`PublicRecruitPost`、`PublicBattleReport`、`Comment`、`Report` 等对象。
4. 明确 Community 不直接公开源 `scenario`、raw export、raw events、账号隐私和未授权素材。
5. 给 DeepSeek 后续实现提供可执行批次、测试命令、启动门槛和禁止事项。

## 非目标

- 不在本轮实现 `/api/community`。
- 不实现公开模组市场页面。
- 不实现招募广场页面。
- 不实现评论、收藏、评分、关注、私信。
- 不实现举报后台和审核 UI。
- 不实现付费模组、收益结算、版权平台。
- 不让 AI 自动决定公开、拒绝、下架、封禁或通过举报。
- 不让 Community 影响 Room、AI、Transaction、State、Projection、Journal 主链路。

## 用户角色

| 角色 | 诉求 | 权限边界 |
| --- | --- | --- |
| Visitor | 浏览公开模组、公开招募、公开战报、公开主页 | 只能看 `published` 且脱敏的内容 |
| Player | 收藏内容、评论评分、未来报名公开团、显式分享战报 | 只能管理自己的互动与显式公开内容 |
| Host | 发布公开招募、使用公开模组、显式分享战报 | 不能公开玩家私密内容和未脱敏剧本真相 |
| Author | 发布和维护模组版本 | 只能发布自己有权限的草稿和授权素材 |
| Moderator | 未来处理评论、举报和下架 | 当前是未来角色，不在本轮代码内新增 |
| Admin | 全局审核、下架、恢复、封禁、查看审计 | 当前有 admin 角色，但缺社区审核工作台 |
| AI-Keeper | 未来辅助标签、摘要和风险提示 | 不能自动发布、自动下架、自动封禁 |
| DeepSeek 执行者 | 后续按批次补代码 | 必须先读当前 Module / Safety / Schedule / Admin 代码与测试 |

## 产品范围

### v1 进入

- 社区边界和对象分层设计；
- 公开发布白名单和禁止字段；
- 发布状态、举报状态、审核状态与审计字段；
- PublicProfile 默认隐私；
- PublishedModule 与源 `scenario` 的隔离；
- PublicBattleReport 的显式发布与成员同意模型；
- 评论、评分、收藏的反滥用口径；
- Community 工程启动门槛。

### v1 不进入

- 公开社区页面、列表、搜索、推荐；
- Community 数据表迁移和 API；
- 评论、收藏、评分、关注、举报的真实实现；
- 付费、收益、活动运营、创作者认证；
- Community 对现有 Room / AI / State / Projection 的行为改造。

## 产品分区

| 分区 | 主要对象 | 第一阶段口径 |
| --- | --- | --- |
| 模组市场 | `PublishedModule`、`ModuleVersion`、`PublicAssetLicense` | 必须建立在 Module 的公开版本边界之上 |
| 招募广场 | `PublicRecruitPost` | 依赖 Schedule；Community 只做公开发现，不接管报名审批 |
| 用户主页 | `PublicProfile` | 默认最小公开，只展示用户显式公开内容 |
| 内容互动 | `Comment`、`Rating`、`Favorite` | 先写规则，不默认实现 |
| 战报分享 | `PublicBattleReport` | 来源于 Journal/export，但必须显式发布且再脱敏 |
| 社区治理 | `Report`、`ModerationCase`、`CommunityAudit` | 依赖 Admin/Ops；本轮先写对象和状态 |

## 当前代码基础

| 当前表或接口 | 可复用价值 | 不能直接做的事 |
| --- | --- | --- |
| `accounts` | 账号、显示名、角色权限 | 不能直接当公开主页，缺隐私和公开资料层 |
| `scenarios` | 模组草稿来源、标题、质量报告 | 不能直接公开 `raw_text`、truth、ending、原始路径 |
| `scenario_assets` | 素材来源 | 缺授权、可公开范围和审核字段 |
| `rooms` | 招募和战报的来源房间 | 不能公开 owner token、私密状态和内部关系 |
| `events` | replay 和战报原始素材 | 不能把 raw events 直接给社区 |
| `campaign_archives` | 结局摘要与高光来源 | 可能含剧透，需要显式发布和再过滤 |
| `spoiler_sensitive_items` | 发布前剧透风险索引 | 只是索引，不是社区审核结果 |
| `spoiler_audits` | 反剧透审计 | admin-only，不进 Community 公开页 |
| `/api/admin/accounts` | 后台账号管理 | 不是用户公开主页系统 |
| `/api/admin/scenarios` | 后台剧本管理 | 不是公开模组市场 |
| `/api/rooms/{room_id}/export` | 战报导出 | 当前 public scope 不能直接社区化 |
| `/api/rooms/{room_id}/replay` | public replay 原始材料 | 不是 Community 分享链接 |

## Community 数据分层

| 层级 | 数据对象 | 说明 |
| --- | --- | --- |
| L0 `AccountIdentity` | 登录账号、角色、权限 | 社区身份基础 |
| L1 `PublicProfile` | 公开昵称、简介、头像、可见性 | 用户公开资料层 |
| L2 `SourceModule` | `scenario` / Module 草稿 | 发布来源层，不对 Visitor 公开 |
| L3 `PublishedModule` | 公开模组主对象 | 公开发现层 |
| L4 `ModuleVersion` | 公开模组每次发布快照 | 审核、回滚、版本管理 |
| L5 `PublicAssetLicense` | 素材授权与公开许可 | 发布素材门槛 |
| L6 `PublicRecruitPost` | 公开招募入口 | 社区发现层 |
| L7 `PublicBattleReport` | 显式发布的脱敏战报 | 公开分享层 |
| L8 `CommunityInteraction` | `Comment` / `Rating` / `Favorite` | 互动层 |
| L9 `Report` | 举报请求 | 治理入口 |
| L10 `ModerationCase` | 审核工单 | 下架、恢复、驳回、申诉 |
| L11 `CommunityAudit` | 管理操作与状态变更留痕 | Admin/Ops 审计 |
| L12 `VisibilityPolicy` | `public/private/hidden/removed` | 可见性控制策略 |
| L13 `CommunityNotification` | 审核结果、评论结果通知 | 依赖 Channel / Ops |

关键边界：

- `AccountIdentity` 不等于 `PublicProfile`；
- `SourceModule` 不等于 `PublishedModule`；
- `PublishedModule` 不等于源 `scenario`；
- `PublicBattleReport` 不等于 raw export / replay；
- `Report` 不等于 `ModerationCase`；
- `CommunityAudit` 不进入公开页。

## DTO 契约

### 最小 DTO 集合

- `PublicProfileDTO`
- `PublicProfileEditDTO`
- `PublishedModuleListItemDTO`
- `PublishedModuleDetailDTO`
- `ModuleVersionPublicDTO`
- `ModulePublishDraftDTO`
- `ModuleReviewRequestDTO`
- `ModuleReviewResultDTO`
- `PublicRecruitPostDTO`
- `PublicBattleReportDTO`
- `CommunityPostDTO`
- `CommentDTO`
- `RatingDTO`
- `FavoriteDTO`
- `ReportRequestDTO`
- `ReportResultDTO`
- `ModerationCaseDTO`
- `ModerationDecisionDTO`
- `CommunityAuditDTO`
- `CommunityApiErrorDTO`

### 关键 DTO 示例

#### `PublishedModuleListItemDTO`

```json
{
  "publishedModuleId": "pm_xxx",
  "title": "公开标题",
  "publicSummary": "公开简介",
  "ruleset": "CoC 7e",
  "recommendedPlayers": "2-4",
  "estimatedDuration": "3-4h",
  "tags": ["investigation"],
  "contentWarnings": ["horror"],
  "authorDisplayName": "作者公开名",
  "status": "published",
  "currentVersion": "1.0.0"
}
```

#### `PublicBattleReportDTO`

```json
{
  "reportId": "report_xxx",
  "title": "公开战报标题",
  "publicPayload": {},
  "visibility": "public|unlisted|hidden",
  "status": "draft|reviewing|published|hidden|archived",
  "createdBy": "acct_xxx"
}
```

#### `ModerationCaseDTO`

```json
{
  "caseId": "case_xxx",
  "sourceReportId": "rep_xxx",
  "targetType": "published_module",
  "targetId": "pm_xxx",
  "status": "triaged",
  "decision": null,
  "publicResultSummary": null,
  "resolvedAt": null
}
```

DTO 总约束：

- 公开页面只接收显式 Community DTO；
- 不允许把 `accounts`、`scenarios`、`events`、`campaign_archives`、`spoiler_audits` 原始对象直接返回；
- 不允许公开 token、`raw_text`、truth、ending、隐藏 NPC、隐藏线索、原始 PDF 路径、本地路径、RAG chunk、AI prompt、内部审核备注。

## 状态机

### 发布对象状态

适用对象：

- `PublishedModule`
- `PublicBattleReport`
- `CommunityPost`
- `PublicRecruitPost`
- `PublicProfile`

状态机：

```text
draft -> reviewing -> published -> hidden -> published
reviewing -> rejected
published -> archived
rejected -> draft
```

### Comment 状态

```text
visible -> hidden -> visible
visible -> deleted
visible -> removed
hidden -> removed
```

说明：

- `deleted` 表示作者删除自己的内容；
- `removed` 表示管理员按治理规则移除；
- `Comment` 不使用 `published` 语义。

### Report 状态

```text
submitted -> triaged -> action_required -> resolved
triaged -> dismissed
dismissed -> appealed
resolved -> appealed
appealed -> resolved
```

### ModerationCase 状态

```text
open -> investigating -> decided -> archived
decided -> reopened
```

## PublishedModule 边界

`PublishedModule` 必须和源 `scenario` 硬隔离：

- 公开响应只能使用 `public_payload` 或 `module_version_public_payload`；
- `source_scenario_id` 只作为后台关联，不进入 Visitor DTO；
- `public_payload` 只允许包含公开标题、简介、规则系统、人数、时长、标签、内容警示、公开素材封面、非剧透质量摘要；
- 不允许包含 `raw_text`、完整 `knowledge_graph`、truth、ending、隐藏 NPC、隐藏线索、原始 PDF 路径、本地路径、RAG chunk、AI prompt；
- 未授权素材不得进入公开 payload。

这条边界必须与 `19-Module` 的 `ModuleDraft / ModuleVersion / PublishState` 保持一致。

## PublicBattleReport 边界

`PublicBattleReport` 必须满足以下发布条件：

1. source room owner 或授权成员显式创建分享；
2. `public_payload` 必须来自 Safety 的 `public_export` 口径或等价安全构建流程；
3. 不得直接使用 raw events、raw replay、raw archive；
4. 玩家角色名、高光片段、个人行动展示，默认需要成员同意或匿名化；
5. `player-only`、`host-only`、hidden truth、private clue 永不进入公开战报；
6. 已发布后如成员撤回同意，必须允许隐藏对应个人信息或下架报告。

进入工程前仍需补充的同意粒度问题：

- 同意是按房间成员、按角色，还是按片段；
- 默认是匿名角色名，还是完全移除个人行动；
- 撤回同意后历史公开链接如何处理。

## PublicProfile 默认隐私

`PublicProfile` 默认最小公开：

- 不公开邮箱、手机号、登录凭证、account token；
- 不公开私密房间历史；
- 不公开角色详情；
- 不公开收藏，除非用户显式公开；
- 不公开出勤、举报、审核记录；
- 只展示 `displayName`、`bio`、`avatar` 与用户显式公开的作品、招募或战报。

真正进入 `Community-4` 前还必须补清：

- `profileId / slug` 是否可变；
- `slug` 抢占和保留词如何处理；
- `displayName` 是否允许重复；
- profile URL 是以 `slug`、`accountId` 还是其他公开标识为准。

## 评论、评分、收藏

### Comment

- 仅登录用户可创建；
- 必须有限速；
- 作者可删除自己的评论；
- 内容作者可隐藏自己内容下的违规评论或请求处理；
- Admin/Ops 可执行 `hidden` / `removed`；
- 评论不写入房间事件流，不影响游戏状态。

### Rating

- 同一账号对同一目标只能一条；
- 重复评分应更新而不是新增；
- 评分变更必须记录 `updated_at`；
- “体验后评分”可作为后续约束，不在本轮强制。

### Favorite

- 默认私有；
- 不进入公开主页，除非用户显式公开；
- 取消收藏不影响目标对象。

## 举报、审核与审计

### `ReportRequestDTO`

- `targetType`
- `targetId`
- `reasonCode`
- `detail?`
- `reporterAccountId`
- `createdAt`

### `ModerationCaseDTO`

- `caseId`
- `sourceReportId?`
- `targetType`
- `targetId`
- `assignedAdminId?`
- `status`
- `decision`
- `internalNote?`
- `publicResultSummary?`
- `createdAt`
- `resolvedAt`

### `ModerationDecisionDTO`

- `action: hide|restore|reject_report|remove|warn_author`
- `reason`
- `notifyAuthor`
- `notifyReporter`

硬规则：

- 举报人身份不展示给被举报作者；
- 内部备注不进公开页；
- Admin 操作必须写入 `CommunityAudit`；
- Moderator 是未来角色；当前实现阶段可先 `admin-only`；
- 不自动封禁，不让 AI 自动处理举报。

## 授权素材边界

公开素材至少需要以下字段：

- `assetId`
- `licenseType`
- `publicUseAllowed`
- `attribution?`
- `source?`
- `reviewerChecked?`

硬规则：

- 未授权素材不得进入 `PublishedModule` 或 `PublicBattleReport` 的公开 payload；
- 原始 PDF 不得直接公开下载；
- 本地路径和 `storageKey` 不得出现在公开页面。

在进入 `Community-5` 前，工程回执还必须说明：

- `author` 是否必须是 `source_scenario` owner；
- Admin 是否允许代管发布；
- 协作者模型如何处理；
- 导入者和作者是否等价。

## 与其他模块关系

- User 提供账号、公开身份基础和角色权限；
- Module 提供模组草稿、结构化数据和版本来源；
- Safety 提供脱敏、反剧透、visibility helper 和 `public_export` 边界；
- Schedule 提供招募与排期数据，Community 只做公开发现入口；
- Journal 提供 replay/export 原始材料，Community 只接收显式发布后的脱敏版本；
- Asset 提供素材与授权字段；
- Admin/Ops 提供审核、下架、恢复、申诉、封禁和审计能力；
- AI-Keeper 只能辅助摘要、标签和风险提示，不能自动做治理决定。

## 工程启动门槛

`Community-4` 之前必须满足：

1. `21-Safety` 的 `public_export` / visibility helper 工程口径已通过；
2. `19-Module` 的 `public module payload / version boundary` 已通过；
3. `22-Schedule` 的 `RecruitPostPublicDTO / Application boundary` 已通过；
4. `24-Admin/Ops` 的 moderation / audit 最小口径已通过；
5. 用户明确确认进入 Community 工程实现。

补充规则：

- `Community-1` 如果补 public safety 测试，只允许验证和消费 Safety helper，不允许在 Community 内复制或改写一套 visibility 规则；
- 本次文档评审通过只放行 `Community-0` 到 `Community-3`；
- `Community-4+` 仍然不是默认批准状态。

若以上条件未满足，Community 只停留在文档和测试前置阶段。

## 验收标准

### 文档阶段

- 明确当前没有 Community 实现；
- 三份文档统一写出当前阶段说明；
- Community 数据分层、DTO 契约、状态机、默认隐私、成员同意、审核与审计边界完整；
- `Community-4+` 被明确标记为 gated，不默认进入工程；
- 不要求本轮实现 `/api/community`、社区表或社区页面。

### 工程启动前

- Safety 的 `public_export` / visibility helper 已收口；
- Module 的公开 payload 与源数据边界已收口；
- Schedule 的公开招募 DTO 与报名审批边界已收口；
- Admin/Ops 有最小审核与审计设计；
- 用户再次确认进入社区工程。

### 工程实现后

- 未审核内容不出现在公开列表；
- `PublishedModule` 不含 `raw_text`、truth、ending、隐藏线索、隐藏 NPC、本地路径、AI prompt；
- `PublicBattleReport` 不含 `host-only`、`player-only`、token、hidden truth、private clue；
- `PublicProfile` 默认不公开私密房间、角色详情、收藏、举报和审核记录；
- 评论、评分、收藏、举报都绑定账号并有状态与反滥用策略；
- 举报、下架、恢复和驳回都进入 `CommunityAudit`。

### 工程回执必须补充说明

- `Community-1` 是否只消费 Safety helper，而未在 Community 内复制 visibility 规则；
- `PublicProfile` 的 `profileId / slug / displayName` 策略；
- `PublishedModule` 的作者授权模型；
- `PublicBattleReport` 的同意粒度与撤回同意后的处理策略；
- 是否仍明确 `Community-4+` 未经用户确认不得启动。
