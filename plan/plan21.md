# AI-Keeper 第一性原理补漏修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` task-by-task 执行。每个 Task 完成后跑对应测试并小提交。

**Goal:** 把项目从“功能块已存在”收束成一条可靠主流程：登录身份明确、房主创建并启动房间、玩家加入并持久化状态、AI 裁决写入单一状态源、事件实时投影、接口权限不漏。

**Architecture:** 以 `account_token + owner_token + player_token` 三类身份为边界；以 `StateService` 作为游戏状态唯一写入口；以统一事件 dispatcher 负责“写审计日志 + 实时 WS 推送”。先修安全和数据一致性，再补 Host/Player 主流程 UI。

**Tech Stack:** FastAPI + PostgreSQL/pgvector + React/Vite + pytest + TypeScript。

---

## Summary

- 第一优先级：修 Git 提交边界、身份鉴权、公开接口泄漏、Host WS 越权。
- 第二优先级：修房主/玩家主流程，支持单机多号测试。
- 第三优先级：统一状态持久化与事件投影，避免 AI 裁决、地图、日志、玩家状态各写各的。
- 第四优先级：补测试，让之后 DeepSeek 或其他 agent 改代码不会再把主流程撞散。

---

## Task 1: Git 与仓库边界清理

**目标:** 保证后续提交不会把缓存、构建产物、本地数据库混进主线，也不会漏掉新拆包源码。

**Files:**
- Create/Modify: `G:\hermes-agent-workplace\D&D\CodeX-aikeeper\.gitignore`
- Inspect: `src/server/ai/`, `src/server/engine/`, `src/server/events/`, `src/server/host/`, `src/server/player/`, `src/server/scenario/`
- Do not commit: `src/client/dist/`, `src/client/node_modules/.vite/`, `data/*.db*`, `__pycache__/`, `.pytest-*`

**Implementation:**
- 新增 `.gitignore`，至少包含：

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.pytest-tmp-*/
*.db
*.db-shm
*.db-wal

src/client/dist/
src/client/node_modules/
src/client/node_modules/.vite/

data/character_presets/
data/scenario_assets/
.env
.env.*
```

- 检查是否已有 `src/client/node_modules/.vite` 被 Git 跟踪。若已跟踪，使用 `git rm -r --cached src/client/node_modules/.vite` 从索引移除，但不要删除本地文件。
- 将新拆分后的源码目录纳入版本库，确认旧文件删除是重构意图，不是误删。

**Verification:**
- Run: `git status --short`
- Expected:
  - 不再出现 `.vite`、`dist`、本地数据库、缓存文件。
  - 新的 `src/server/*/` 包和新前端页面组件都可见并准备提交。
- Commit: `chore: clean repository boundaries`

---

## Task 2: 统一身份模型与前端多账号槽

**目标:** 支持同一浏览器里 admin、host、多个 player 并存测试；所有页面不再直接读写裸 `localStorage`。

**Files:**
- Modify: `src/client/src/shared/identity.ts`
- Modify: `src/client/src/App.tsx`
- Modify: `src/client/src/pages/LoginPage.tsx`
- Modify: `src/client/src/pages/HostCreate.tsx`
- Modify: `src/client/src/pages/HostLobby.tsx`
- Modify: `src/client/src/pages/HostStage.tsx`
- Modify: `src/client/src/pages/PlayerJoinPage.tsx`
- Modify: `src/client/src/pages/PlayerActionPage.tsx`
- Modify: `src/client/src/pages/PlayerCharacter.tsx`

**Rules:**
- `account_token`: 登录账号身份，用于 admin/host/player 账号级操作。
- `owner_token`: 房主对某个房间的管理 token，只属于该房间。
- `player_token`: 玩家角色进入某个房间后的身份 token。
- 开房者必须登录，且角色为 `host` 或 `admin`。
- 玩家加入房间也必须登录，但一个账号可以加入多个房间。
- 前端任何页面不得直接 `localStorage.getItem("account_token")`；统一改成 `getSlotValue("account_token")`。
- 前端任何页面不得直接 `localStorage.setItem("player_token")`；统一改成 `setSlotValue("player_token", token)`。

**Implementation:**
- 在 `App.tsx` 顶层渲染 `IdentitySwitcher`，让单机多号测试有入口。
- `LoginPage` 登录成功后调用 `setSlotValue("account_token", token)` 和 `setSlotValue("account", JSON.stringify(account))`。
- `PlayerJoinPage` 加入成功后写入当前 identity slot 的 `player_token`、`player_room_id`、`player_character_id`。
- `HostCreate` 创建房间成功后写入当前 identity slot 的 `owner_token`、`host_room_id`。
- `HostLobby`、`HostStage` 读取 owner token 时优先用 slot，不再依赖全局 legacy storage。
- 保留 legacy fallback，但只作为迁移兼容，不作为新代码入口。

**Verification:**
- Run: `rg "localStorage\\.(getItem|setItem|removeItem)" src/client/src`
- Expected:
  - 只允许 `shared/identity.ts` 和极少数迁移/清理代码出现。
- Run: `cd src/client; node ./node_modules/typescript/bin/tsc --noEmit`
- Expected: PASS。
- Commit: `feat: unify client identity slots`

---

## Task 3: 房间、剧本、RAG 接口鉴权与脱敏

**目标:** 任何玩家不能拿到 owner token；任何未授权用户不能导入剧本、创建房间、索引 RAG、读取非本房间资料。

**Files:**
- Modify: `src/server/router_rooms.py`
- Modify: `src/server/scenario/router_scenarios.py`
- Modify: `src/server/rag_router.py`
- Modify: `src/server/ai/rag.py`
- Test: `tests/server/test_room_security.py`
- Test: `tests/server/test_rag_security.py`

**Implementation:**
- `GET /api/rooms/{room_id}` 返回脱敏 DTO：
  - allowed: `room_id`, `status`, `scenario_id`, `scenario_title`, `created_at`, `players/count`, `started_at`
  - forbidden: `owner_token`, `owner_account_id`, internal DB-only fields
- 废弃或保护公开的 `POST /api/scenarios/import-pdf`：
  - 未登录返回 `401`
  - 非 admin 返回 `403`
  - 保留 `/api/admin/scenarios/import-pdf` 作为正式入口
- 废弃或保护 `POST /api/scenarios/{scenario_id}/create-room`：
  - 必须登录 host/admin
  - 创建房间时写入 `owner_account_id`
  - 返回 `owner_token`
- `rag_router.py` 全部写操作要求 admin 或 room owner：
  - `index`, `index-character`, `index-npc`, `index-rules` 要 admin/owner
  - `search` 要 room owner、room player 或 admin
  - `rule-docs/stats` 至少要求登录
- `RAGStore.search(room_id=...)` 修改过滤策略：
  - 允许本房间内容
  - 允许全局规则书 `source_type = "rule"`
  - 不允许任意 `room_id IS NULL` 的 asset/NPC 泄漏给所有房间
  - scenario 级内容只能在房间绑定该 scenario 后可见

**Verification:**
- Add tests:
  - 普通玩家请求房间详情时响应不含 `owner_token`
  - 未登录导入剧本返回 `401`
  - 非 owner 搜索房间 RAG 返回 `403`
  - 本房间玩家可搜索规则书和本房间资料
  - A 房间不能搜到 B 房间 NPC/素材
- Run: `python -m pytest tests/server/test_room_security.py tests/server/test_rag_security.py -q`
- Expected: PASS。
- Commit: `fix: secure room scenario and rag boundaries`

---

## Task 4: Host 创建、选剧本、开局主流程

**目标:** Host 端不再像 admin 后台；它应该是一条清楚的开房流程：登录 → 选剧本 → 创建房间 → 等玩家 → 确认 ready → 开始。

**Files:**
- Modify: `src/server/router_rooms.py`
- Modify: `src/client/src/pages/HostCreate.tsx`
- Modify: `src/client/src/pages/HostLobby.tsx`
- Modify: `src/client/src/pages/HostStage.tsx`
- Test: `tests/server/test_host_room_lifecycle.py`

**Implementation:**
- 新增或固化 Host 可读剧本列表：
  - `GET /api/scenarios/available`
  - 登录 host/admin 可访问
  - 返回 `scenario_id`, `title`, `status`, `asset_count`, `created_at`
- `HostCreate` 必须先选剧本，再创建房间。
- `POST /api/rooms`：
  - 必须登录 host/admin
  - `scenario_id` 必填
  - 写入 `owner_account_id`
  - 返回 `room_id`, `owner_token`, `status: lobby`
- `HostLobby`：
  - 显示玩家昵称、调查员名、HP/SAN、ready 状态、连接状态
  - 所有玩家 ready 时启用“开始游戏”
  - 无玩家时不能开始，除非传 `force=true` 且 UI 明确显示“单人调试启动”
- `POST /api/rooms/{room_id}/start`：
  - 只有 owner/admin 可调用
  - 默认要求至少 1 名玩家
  - 默认要求所有玩家 ready
  - 成功后写 `status=active`, `started_at`
- `HostStage`：
  - 进入前校验当前账号/owner token 是否有 host 权限
  - reset/pause/start 等按钮统一带 `Authorization` 或 `X-Owner-Token`

**Verification:**
- Add tests:
  - 未登录创建房间 401
  - player 账号创建房间 403
  - host 创建房间必须带 scenario_id
  - host 创建后 `owner_account_id` 正确
  - 房间无玩家时 start 返回 409
  - 有未 ready 玩家时 start 返回 409
  - 全部 ready 后 start 返回 active
- Run: `python -m pytest tests/server/test_host_room_lifecycle.py -q`
- Expected: PASS。
- Commit: `feat: complete host room lifecycle`

---

## Task 5: Host WebSocket 与实时事件鉴权

**目标:** 只有真正房主/admin 能打开 Host WS；玩家只能打开自己的 Player WS。

**Files:**
- Modify: `src/server/main.py`
- Modify: `src/server/host/router_host.py`
- Modify: `src/server/events/dispatcher.py` 或现有 dispatcher 模块
- Modify: `src/client/src/pages/HostStage.tsx`
- Test: `tests/server/test_ws_auth.py`

**Implementation:**
- Host WS URL 必须带身份：
  - `ws://.../ws?room={roomId}&role=host&ownerToken={ownerToken}`
  - 或使用登录 account token 的 WS 子协议/header；若浏览器限制 header，则 query token 可接受，但后端不得记录完整 token 到日志。
- `host_ws_endpoint` 进入前校验：
  - `ownerToken` 匹配房间 owner token，或
  - `account_token` 对应 admin/owner account
- Player WS 保持 `player_token` 校验。
- `GET /api/host/{room_id}/hud` 增加相同 owner/admin 校验。
- 未授权 WS 直接 close，使用明确 close code，例如 `1008 policy violation`。
- Host WS 接收到控制类消息时再次校验 room ownership，不信任客户端 role。

**Verification:**
- Add tests:
  - 无 token 连接 host WS 被拒
  - 错 token 连接 host WS 被拒
  - owner token 可连接 host WS
  - admin account token 可连接 host WS
  - 玩家 token 不能连接 host WS
- Run: `python -m pytest tests/server/test_ws_auth.py -q`
- Expected: PASS。
- Commit: `fix: authenticate host websocket`

---

## Task 6: 状态持久化单一写入口

**目标:** AI 裁决、技能检定、移动、线索、地图、玩家属性变化都通过一个状态服务写入，避免双增版本、事件乱序、半提交。

**Files:**
- Modify: `src/server/engine/state_service.py`
- Modify: `src/server/engine/resolution_pipeline.py`
- Modify: `src/server/events/event_log.py`
- Modify: `src/server/engine/projection.py`
- Test: `tests/server/test_state_service_consistency.py`
- Test: `tests/server/test_resolution_pipeline_state.py`

**Implementation:**
- `ResolutionPipeline` 不再直接更新 `rooms.state_version`。
- `ResolutionPipeline` 只产出 `ResolutionResult` 和状态变更请求。
- `StateService.apply_change()` 成为唯一负责：
  - 校验版本
  - 应用 JSON patch / domain patch
  - 更新角色 runtime state
  - 更新 room state_version
  - 写 event log
  - 调用 dispatcher 发送 live event
  - commit
- `EventLog.log_event()` 增加可选参数 `commit: bool = True`。
  - 在事务内由 StateService 调用时使用 `commit=False`
  - 单独写审计事件时保留默认 `commit=True`
- `ProjectionDispatcher.emit()` 统一负责：
  - 先写 event log
  - 拿到 sequence
  - 再发送 WS live event，live payload 必须带 `roomSequence`
- 修 `clue_shares` 写入：
  - 若 schema 不含 `room_id`，不要写该字段
  - 不允许吞异常；失败要让测试暴露
- encounter/map/player runtime state 未实现的 patch 类型：
  - 明确返回 rejected/unsupported
  - 不静默成功

**Verification:**
- Add tests:
  - 一次 AI resolution 只让 `state_version` 增加 1
  - event log sequence 与 live `roomSequence` 一致
  - StateService 写 clue share 不吞异常
  - unsupported patch 返回明确错误
  - projection 不早于状态提交
- Run: `python -m pytest tests/server/test_state_service_consistency.py tests/server/test_resolution_pipeline_state.py -q`
- Expected: PASS。
- Commit: `fix: centralize state writes and event projection`

---

## Task 7: 玩家持久状态与房间内状态模型

**目标:** 玩家不只是“有一张车卡”，还要有可持续变化的游玩状态：HP/SAN/MP/LUCK、位置、ready、连接、当前场景、背包、线索、异常状态。

**Files:**
- Modify: `src/server/db_adapter.py`
- Modify: `src/server/player/router_player.py`
- Modify: `src/server/engine/state_service.py`
- Modify: `src/client/src/pages/PlayerCharacter.tsx`
- Modify: `src/client/src/pages/PlayerActionPage.tsx`
- Test: `tests/server/test_player_runtime_state.py`

**Data rules:**
- `characters.xlsx_data` 保存原始解析后的静态车卡。
- 新增/固化 runtime state 表或 JSONB 字段保存可变状态：
  - `hp_current`, `san_current`, `mp_current`, `luck_current`
  - `location_id`
  - `conditions`
  - `inventory`
  - `clue_ids`
  - `ready_status`
  - `connection_status`
- 玩家加入房间时，从车卡初始化 runtime state。
- 技能值默认来自静态车卡；HP/SAN/MP/LUCK 显示 runtime current/max。
- 玩家 ready 是房间内角色状态，不是账号状态。

**Verification:**
- Add tests:
  - 玩家导入车卡后 runtime state 初始化正确
  - HP/SAN 变化只改 runtime，不改原始 xlsx_data
  - 玩家 ready 后 Host lobby 可见
  - 玩家重连后 runtime state 保持
- Run: `python -m pytest tests/server/test_player_runtime_state.py -q`
- Expected: PASS。
- Commit: `feat: persist player runtime state`

---

## Task 8: 场景、地图、日志页面分离

**目标:** Host 的日志和地图不再复用同一个 UI；地图显示地图状态，日志显示事件时间线。

**Files:**
- Modify: `src/client/src/pages/HostStage.tsx`
- Modify: `src/client/src/components/HostLogsPanel.tsx`
- Modify/Create: `src/client/src/components/HostMapPanel.tsx`
- Modify: `src/server/host/router_host.py`
- Test: front-end TypeScript build

**Implementation:**
- Host tab `日志`：
  - 显示事件类型筛选、关键词搜索、时间线列表、导出按钮
  - 使用 event log 数据或现有 HostLogsPanel
- Host tab `地图`：
  - 显示当前场景名、玩家位置列表、地图区域/节点占位
  - 没有真实地图时显示“当前剧本暂无地图素材”
  - 不显示日志筛选控件
- Host 右侧调查员监控持续显示真实 joined players。
- 若 WS 收到 `map_updated`, `player_moved`, `map_revealed`，只更新地图面板相关状态。
- 若 WS 收到 `audit_log`, `s2c_action_completed`, `public_observation`，只更新日志/叙事相关状态。

**Verification:**
- Run: `cd src/client; node ./node_modules/typescript/bin/tsc --noEmit`
- Expected: PASS。
- Manual:
  - `/host/{roomId}/stage` 点“日志”看到日志 UI
  - 点“地图”看到地图 UI
  - 两者不再长成同一个面板
- Commit: `fix: separate host map and log panels`

---

## Task 9: 测试套件与旧测试修正

**目标:** 让测试表达现在的真实产品规则，而不是旧的匿名开房模型。

**Files:**
- Modify: `tests/server/test_rooms.py`
- Add: `tests/server/test_host_room_lifecycle.py`
- Add: `tests/server/test_room_security.py`
- Add: `tests/server/test_ws_auth.py`
- Add: `tests/server/test_state_service_consistency.py`
- Add: `tests/server/test_player_runtime_state.py`

**Implementation:**
- 更新 `test_rooms.py`：
  - 创建房间前先创建/login host account
  - 创建房间必须传 scenario_id
  - start room 必须带 owner/admin 身份
- 增加 test fixtures：
  - `admin_account`
  - `host_account`
  - `player_account`
  - `scenario`
  - `room_with_owner`
  - `joined_ready_player`
- 所有测试不得依赖真实 DeepSeek key。
- AI 调用必须 stub/mock。
- RAG 测试可以使用临时 pgvector 测试库；若没有 pgvector，则跳过带清晰 reason 的 integration 测试，纯过滤逻辑必须保留单测。

**Verification:**
- Run: `python -m pytest tests/server/test_rooms.py -q`
- Expected: PASS。
- Run: `python -m pytest tests/server -q`
- Expected: PASS 或仅明确 skip 外部依赖测试。
- Run: `cd src/client; node ./node_modules/typescript/bin/tsc --noEmit`
- Expected: PASS。
- Run: `cd src/client; node ./node_modules/vite/bin/vite.js build`
- Expected: PASS。
- Commit: `test: align coverage with authenticated game flow`

---

## Task 10: 最终人工验收主流程

**目标:** 用真实浏览器走完整链路，确认不是只通过测试。

**Manual Scenario:**
1. 打开 `/login`，登录 admin。
2. 进入 admin 剧本页，导入一个剧本 PDF，上传多个素材文件。
3. 切到 host identity，登录 host。
4. 打开 `/host/create`，选择剧本，创建房间。
5. 进入 `/host/{roomId}` lobby，确认看到房间码、剧本名、玩家列表、开始按钮禁用。
6. 新开 identity slot，登录 player A。
7. 打开 `/player/join`，输入房间码，选择预设车卡，加入房间。
8. Player A 设置 ready。
9. Host lobby 看到 Player A 昵称、调查员名、HP/SAN、ready。
10. Host 点击开始，进入 `/host/{roomId}/stage`。
11. Player A 进入 `/player/{roomId}`，提交普通行动。
12. Host 舞台收到叙事投影、行动完成、日志事件。
13. Player A 看到行动结果。
14. Host 分别点“日志”“地图”，确认页面不同且不互相污染。
15. 刷新 Host 和 Player 页面，确认房间状态、玩家状态、日志仍在。

**Acceptance:**
- 不需要手动改数据库。
- 不需要从 admin 后台强行改房间状态才能开始。
- 单浏览器可切换多个账号测试。
- 普通玩家不能打开 Host stage。
- 知道房间号不能拿到 owner token。
- AI 裁决后状态版本只增一次。
- 日志和地图页面明显分离。

---

## Assumptions

- 本轮不做正式 Alembic 迁移框架；仍可使用 idempotent `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`。
- 本轮不做真实生产级 RBAC 后台，只定义最小可用角色：`admin`, `host`, `player`。
- DeepSeek API 不作为默认测试依赖；所有 AI 路径默认 mock/stub。
- 不删除旧旁支文件，除非测试和 import 已证明它们会造成冲突。
- 不提交 `dist`、`.vite`、本地数据库、预设车卡、上传素材。
- 完成后交回给 Codex 做第二轮 code review，重点复查：权限边界、状态事务、事件顺序、测试是否真实覆盖主流程。
