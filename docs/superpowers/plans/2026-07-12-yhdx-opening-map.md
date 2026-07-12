# 《向火独行》开局场景与地图图片 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让《向火独行》新房间开局直接呈现条目 1，并将全部图片素材版本化绑定到地图、条目、场景、物品、线索、NPC 或结局。

**Architecture:** 后端从版本化世界书读取场景，从 `scenario_assets` 表解析安全底图候选，并通过 `scenario_asset_bindings` 保存供应商无关的多模态匹配草稿。玩家首页通过 `CampaignHomeDTO.current_scene` 获取 `SoloAdventureRuntime` 与已确认素材的安全投影，继续按钮复用现有地图文字场景与分支动作链。

**Tech Stack:** FastAPI、PostgreSQL、pytest、React、TypeScript、Vitest、Vite、浏览器验收。

## Global Constraints

- 玩家只能读取已确认地图的底图资产。
- 地图底图只保存 `assetId`，不暴露服务器路径。
- 只有已确认且属于房间版本快照的素材绑定可以进入玩家投影。
- 新发布版本只影响新房间；已开始房间继续绑定原版本快照。
- 旧房间和无地图剧本必须继续使用文字模式。
- 所有生产代码先有失败测试，再做最小实现。

---

### Task 1: 版本化地图生成与底图自动识别

**Files:**
- Modify: `src/server/router_admin.py`
- Modify: `src/server/ai/map_generator.py`
- Test: `tests/server/test_map_draft_v2.py`

**Interfaces:**
- Consumes: `scenario_version_id: str | None` 查询参数、`scenario_assets` 表中的图片素材。
- Produces: `_select_map_base_asset(conn, scenario_id) -> dict[str, str]`，返回 `{"assetId": "..."}` 或 `{}`；地图生成结果保留 `baseAsset`。

- [ ] **Step 1: 写失败测试**

覆盖：文件名含 `地图`/`map` 时自动选择；指定草稿版本时使用该版本 `knowledge_graph.scenes`；AI 超时后本地生成仍保留底图。

- [ ] **Step 2: 验证测试失败**

Run: `python -m pytest tests/server/test_map_draft_v2.py -q`

Expected: 底图为空、版本参数未生效或超时测试失败。

- [ ] **Step 3: 最小实现**

在 `router_admin.py` 中按 `original_name` 优先级选择地图图片，校验素材属于当前剧本；地图生成接口接受可选 `scenario_version_id`。使用有限等待时间调用 AI；超时后执行本地 `MapGenerator(api_key="", gateway=None)`，继续传入已选择底图。

- [ ] **Step 4: 验证通过**

Run: `python -m pytest tests/server/test_map_draft_v2.py -q`

Expected: 全部通过。

### Task 2: 管理页底图选择与预览

**Files:**
- Modify: `src/client/src/pages/AdminDashboard.tsx`
- Test: `src/client/tests/admin-dashboard.test.tsx`

**Interfaces:**
- Consumes: 当前剧本素材列表、`ScenarioMapDraft.baseAsset.assetId`、当前选中的 `scenario_version_id`。
- Produces: 地图底图选择器；PATCH 地图时提交 `mapType` 与 `baseAsset`；生成地图时携带版本参数。

- [ ] **Step 1: 写失败测试**

服务端渲染地图审核区，断言存在“地图底图”选择器、`地图.png` 选项、底图预览标识，并断言生成 URL 携带版本 ID 的纯函数输出。

- [ ] **Step 2: 验证测试失败**

Run: `cd src/client; npm run test -- --run tests/admin-dashboard.test.tsx`

Expected: 找不到底图选择器或版本化 URL。

- [ ] **Step 3: 最小实现**

复用现有 `assets` 状态列出图片素材。选择素材时调用地图 PATCH；当 `baseAsset.assetId` 存在时展示受鉴权的管理端图片预览。地图生成请求追加 `scenario_version_id`。

- [ ] **Step 4: 验证通过并构建**

Run: `cd src/client; npm run test -- --run tests/admin-dashboard.test.tsx; npm run build`

Expected: Vitest 与 Vite 构建通过。

### Task 3: 玩家首页当前条目投影

**Files:**
- Modify: `src/server/player/router_campaign_v2.py`
- Modify: `src/client/src/shared/types.ts`
- Modify: `src/client/src/components/CampaignHomePanel.tsx`
- Modify: `src/client/src/pages/PlayerActionPage.tsx`
- Test: `tests/server/test_campaign_v2.py`
- Test: `src/client/tests/campaign-home.test.tsx`

**Interfaces:**
- Produces: `CampaignHomeDTO.current_scene`，字段为 `node_id`、`title`、`text_preview`、`citation`、`choice_count`。
- Consumes: `CampaignHomePanel.onContinueScene: () => void`，由玩家页切换到 `map` 标签。

- [ ] **Step 1: 写后端失败测试**

创建绑定有效单人版本的房间，断言 `/api/player/campaign-home` 只返回当前条目的安全字段，不返回其他节点正文。

- [ ] **Step 2: 验证后端测试失败**

Run: `python -m pytest tests/server/test_campaign_v2.py -q`

Expected: `current_scene` 缺失。

- [ ] **Step 3: 实现安全投影**

调用 `SoloAdventureRuntime.current(room_id)`，截取适合首页的正文预览，保留 citation 与合法选择数量；无单人冒险时返回 `null`。

- [ ] **Step 4: 写前端失败测试**

渲染含 `current_scene` 的首页，断言条目标题、正文预览、“继续当前场景”按钮存在，点击后调用回调。

- [ ] **Step 5: 实现首页卡片与标签切换**

为 `CampaignHomePanel` 增加 `onContinueScene`，在 `PlayerActionPage` 中传入 `() => setTab('map')`。

- [ ] **Step 6: 验证前后端通过**

Run: `python -m pytest tests/server/test_campaign_v2.py -q`

Run: `cd src/client; npm run test -- --run tests/campaign-home.test.tsx; npm run build`

Expected: 全部通过。

### Task 4: 版本化图片素材绑定与管理审核

**Files:**
- Modify: `src/server/db_adapter.py`
- Modify: `src/server/db_pg.py`
- Create: `src/server/scenario/asset_binding.py`
- Modify: `src/server/scenario/import_service.py`
- Modify: `src/server/router_admin.py`
- Modify: `src/client/src/pages/AdminDashboard.tsx`
- Test: `tests/server/test_scenario_asset_bindings.py`
- Test: `src/client/tests/admin-dashboard.test.tsx`

**Interfaces:**
- Produces: `scenario_asset_bindings(binding_id, scenario_version_id, asset_id, target_type, target_key, confidence, evidence, generated_by, status)`。
- Produces: `POST /api/admin/scenarios/{scenario_id}/versions/{version_id}/asset-bindings/generate`、`GET .../asset-bindings`、`PATCH .../asset-bindings/{binding_id}`。
- Consumes: 多模态网关的可选 `bind_scenario_assets(content_package, targets)`；不可用时使用文件名与目标文本的本地建议器，所有非地图建议保持 `draft`。

- [ ] **Step 1: 写失败测试**

覆盖同批图片物化、版本隔离、未确认绑定不投影、确认后可见、目标不存在时拒绝确认，以及既存素材重建建议。

- [ ] **Step 2: 验证测试失败**

Run: `python -m pytest tests/server/test_scenario_asset_bindings.py -q`

Expected: 表、服务和接口不存在。

- [ ] **Step 3: 实现数据表与本地建议器**

两套 schema 初始化入口同时新增表和索引。建议器标准化目标文本，只把精确 `地图`/`map` 建议为 `map`，其余文件名与目标标题命中时生成 `draft`，保存 confidence 与 evidence。

- [ ] **Step 4: 接入供应商无关网关与导入流水线**

导入完成世界书后调用绑定服务；网关不支持时本地建议，不阻断剧本草稿生成。旧素材通过管理接口按指定版本重建。

- [ ] **Step 5: 实现管理审核 UI**

逐图显示缩略图、目标类型、目标键、置信度和依据；管理员可确认、拒绝或修改目标后确认。

- [ ] **Step 6: 验证通过**

Run: `python -m pytest tests/server/test_scenario_asset_bindings.py -q`

Run: `cd src/client; npm run test -- --run tests/admin-dashboard.test.tsx; npm run build`

Expected: 全部通过。

### Task 5: 浏览器验收并继续完整剧本测试

**Files:**
- Create: `docs/loop_runs/2026-07-12-yhdx-manual-polish.md`

**Interfaces:**
- Consumes: 已发布《向火独行》V2、已确认图片/混合地图、已确认条目/内容图片绑定、新房间。
- Produces: 截图证据、失败记录、修复记录和后续测试状态。

- [ ] **Step 1: 发布 V2 并确认地图**

在管理页选择 `地图.png`、审核其他 11 张图片的建议目标、确认地图、确认发布版本 #2。

- [ ] **Step 2: 创建新房间并验证开局**

通过浏览器创建新房、恢复或创建角色、开始房间；断言首页显示条目 1 与已确认场景图，继续后显示完整正文、citation、合法出口和地图底图。

- [ ] **Step 3: 验证首个合法分支**

点击条目 1 的合法出口，完成预览与确认，断言当前条目更新且重连不重复应用。

- [ ] **Step 4: 继续剩余验收**

依次测试自然语义理解、AI 方向控制、战斗和结局；每发现一个阻断问题先复现、写测试、修复、浏览器复验。

- [ ] **Step 5: 最终验证与报告**

Run: `python -m pytest tests/server/test_map_draft_v2.py tests/server/test_campaign_v2.py tests/server/test_scenario_asset_bindings.py tests/server/test_action_lifecycle_v2.py tests/server/test_scenario_import_workflow.py -q`

Run: `cd src/client; npm run test -- --run tests/admin-dashboard.test.tsx tests/campaign-home.test.tsx tests/player-action-controller.test.ts; npm run build`

Run: `git diff --check`

Expected: 所有命令通过，报告记录浏览器证据与剩余非阻断风险。
