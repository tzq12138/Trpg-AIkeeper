# AI-Keeper 返工闭环计划：完成 DeepSeek 上轮未通过项

## Summary

- 本轮只修验收未通过的问题，不新增功能、不重做 UI、不继续扩 AI 能力。
- 目标是让主流程真实可跑：Host 登录后能选剧本、开房、看玩家、启动房间、进入舞台；玩家加入后状态持久；AI 裁决只走一个状态写入口；后端测试不再大面积红。
- 完成后必须交回 Codex 二次验收，重点看：Host WS 鉴权、状态事务、房间开始规则、测试套件、提交边界。

## Hard Rules

- 不提交 `.runtime/`、`dist/`、`node_modules/`、本地数据库、预设车卡、剧本 PDF/xlsx、大型设计素材 zip。
- 不把 API Key 写入代码、日志、测试或文档，只能读环境变量。
- 不新增新页面、新 AI 功能、新地图交互；只修计划列出的断点。
- 每个 Task 完成后跑对应测试，最后跑完整后端测试和前端 build。

---

## Task 1: 清理提交边界与忽略规则

**问题:** 上轮提交混入 `.runtime/*.log`、设计 zip、素材 PDF/xlsx 等非本轮代码资产；`.gitignore` 未忽略 `.runtime/`。

**修改:**
- 更新 `.gitignore`，加入：

```gitignore
.runtime/
src/client/dist/
src/client/node_modules/
*.db
*.db-shm
*.db-wal
__pycache__/
.pytest_cache/
.pytest-tmp-*/
data/character_presets/
data/scenario_assets/
```

- 从 Git 索引移除不该跟踪的本地产物，但不删除本地文件：
  - `.runtime/`
  - `src/client/dist/`
  - 误提交的本地测试素材、规则书 PDF/xlsx、设计 zip，除非它们本来就是项目文档要求保留的正式源码资产。
- 保留源码、测试、必要文档。

**Verification:**
- Run: `git status --short`
- Expected: 不出现 `.runtime/`、`dist/`、`.vite`、本地 DB、临时 PDF/xlsx。
- Commit: `chore: clean tracked runtime artifacts`

---

## Task 2: 修 Host 前端鉴权接入

**问题:** 后端 Host WS 已要求 `ownerToken`，但 `HostLobby` 和 `HostStage` 没带 token，导致房主自己连不上 Host 实时通道；reset/pause/HUD 也缺鉴权。

**修改文件:**
- `src/client/src/pages/HostLobby.tsx`
- `src/client/src/pages/HostStage.tsx`

**修改要求:**
- Host WS URL 必须带 owner token：

```ts
const ownerToken = getSlotValue('owner_token') || '';
const url = `${protocol}//${window.location.hostname}:3001/ws?room=${roomId}&role=host&ownerToken=${encodeURIComponent(ownerToken)}&lastSequence=${lastSeqRef.current}`;
```

- `HostLobby` 的 WS 也必须带 `ownerToken`。
- `HostLobby` fallback 轮询 `/api/host/{roomId}/hud` 必须带：

```ts
headers: { 'X-Owner-Token': getSlotValue('owner_token') || '' }
```

- `HostStage` 的 `reset`、`pause`、`retry-turn`、HUD/地图/遭遇相关 Host API 调用都统一带 `X-Owner-Token`。
- 如果没有 `owner_token`，页面显示“需要房主身份，请从创建房间页进入”，不要静默无限重连。

**Verification:**
- Run: `cd src/client; node ./node_modules/typescript/bin/tsc --noEmit`
- Expected: PASS。
- Manual: 创建房间后进入 lobby/stage，浏览器 Network 中 Host WS URL 含 `ownerToken`，HUD 不再 403。
- Commit: `fix: pass host ownership token from client`

---

## Task 3: 修 Host 创建页剧本列表

**问题:** 后端已有 `/api/scenarios/available`，但 `HostCreate.tsx` 仍请求 `/api/admin/scenarios`，普通 host 无法稳定拿到剧本列表。

**修改文件:**
- `src/client/src/pages/HostCreate.tsx`
- 如有需要，调整 `src/server/scenario/router_scenarios.py`

**修改要求:**
- `HostCreate` 改请求：

```ts
fetch('/api/scenarios/available', {
  headers: { Authorization: `Bearer ${getSlotValue('account_token') || ''}` },
})
```

- 后端 `/api/scenarios/available` 保持只允许 `host/admin`。
- 返回字段至少包括：`scenario_id`, `title`, `status`, `created_at`。
- 前端空列表时显示“暂无可用剧本，请管理员先导入剧本”，不要显示空白选择框。

**Verification:**
- Add/Update test:
  - host 登录可访问 `/api/scenarios/available`
  - player 登录访问返回 403
  - 未登录返回 401
- Run: `python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_room_security.py -q`
- Run: `cd src/client; node ./node_modules/typescript/bin/tsc --noEmit`
- Commit: `fix: use host scenario list for room creation`

---

## Task 4: 修房间开始规则

**问题:** 当前空房间也能 start；测试还把这个错误当成通过条件。

**修改文件:**
- `src/server/router_rooms.py`
- `tests/server/test_rooms.py`
- `tests/server/test_host_room_lifecycle.py`

**后端规则:**
- start 前必须满足：
  - 房间存在
  - 调用者是 owner/admin
  - `scenario_id` 已设置
  - 至少 1 名 `status IN ('active', 'joined')` 的玩家
  - 默认所有玩家 `is_ready = true`
- 未满足时：
  - 无玩家：返回 `409`，detail 为“至少需要一名玩家加入后才能开始”
  - 有未 ready 玩家：返回 `409` 或现有 `status: not_ready`，但 HTTP 状态必须让前端知道这是不可开始
- 如保留调试强制启动：
  - 参数名固定为 `force_start: true`
  - 只有 owner/admin 可用
  - 前端必须明确显示“单人调试启动”
  - 测试必须覆盖 force 与非 force 两种情况

**测试修正:**
- 删除或修改“空房间 start 成功”的测试。
- 新增：
  - empty room start -> 409
  - one not-ready player -> 409/not_ready
  - one ready player -> active
  - force_start empty room -> 允许或不允许，按最终规则固定，不要含糊

**Verification:**
- Run: `python -m pytest tests/server/test_rooms.py tests/server/test_host_room_lifecycle.py -q`
- Expected: PASS。
- Commit: `fix: enforce room start readiness rules`

---

## Task 5: 修 Host 后端相对导入错误

**问题:** `src/server/host/router_host.py` 中多处 `from ...map_persistence` / `from ...engine.projection` 会越过 `src.server` 包，运行时可能 500。

**修改文件:**
- `src/server/host/router_host.py`

**修改要求:**
- 将错误导入全部改成两点相对导入：

```py
from ..map_persistence import ...
from ..engine.projection import ProjectionDispatcher
from ..encounter_persistence import ...
```

- 全文件搜索确认不存在 `from ...`。
- 不改业务逻辑。

**Verification:**
- Run: `rg "from \\.\\.\\." src/server/host src/server/router_rooms.py`
- Expected: 无结果。
- Run: `python -m pytest tests/server/test_host.py tests/server/test_ws_auth.py -q`
- Expected: PASS 或只剩与旧鉴权测试有关的已知失败，必须同步修测试。
- Commit: `fix: correct host package imports`

---

## Task 6: 真正统一状态写入口

**问题:** `ResolutionPipeline` 仍直接 bump `rooms.state_version` 并 commit，然后再调用 `StateService`，没有完成计划中的“唯一状态写入口”。

**修改文件:**
- `src/server/engine/resolution_pipeline.py`
- `src/server/engine/state_service.py`
- `src/server/events/event_log.py`
- `src/server/engine/projection.py`
- `tests/server/test_state_service_consistency.py`
- `tests/server/test_resolution_pipeline.py`

**修改要求:**
- `ResolutionPipeline` 不再直接执行：

```sql
UPDATE rooms SET state_version = state_version + 1
```

- `ResolutionPipeline` 可直接更新 action 状态，但涉及游戏状态变化的内容必须交给 `StateService.apply_change()`。
- `EventLog.log_event()` 支持：

```py
def log_event(..., commit: bool = True) -> int:
```

- `StateService.apply_change()` 内部写 event log 时传 `commit=False`，最后统一 `conn.commit()`。
- `ProjectionDispatcher.emit()` 继续负责“写 events 表 + live WS”，但不得和 StateService 对同一 state patch 重复写两份冲突事件。
- `StateService._apply_clue_changes()` 不得写 `clue_shares.room_id`，因为 schema 没有该字段。
- 不允许吞掉 clue share 写入异常；失败应让测试暴露。
- `encounter_changes` 如果未实现，返回明确 unsupported/rejected，不要静默 `applied = true`。

**Verification:**
- Add/Update tests:
  - 一次带 mutation 的 action resolution 只让 `state_version` 增 1
  - `EventLog.log_event(commit=False)` 不提前提交
  - clue share 写入不访问不存在的 `room_id` 字段
  - unsupported encounter change 不静默成功
- Run: `python -m pytest tests/server/test_state_service_consistency.py tests/server/test_resolution_pipeline.py tests/server/test_state_service.py -q`
- Expected: PASS。
- Commit: `fix: make state service the single state writer`

---

## Task 7: 修测试幂等性与旧主流程测试

**问题:** 新增 fixture 重复插固定 ID 会撞唯一键；大量旧测试仍假设匿名创建房间。

**修改文件:**
- `tests/server/test_rooms.py`
- `tests/server/test_room_security.py`
- `tests/server/test_host_room_lifecycle.py`
- `tests/server/test_archive.py`
- `tests/server/test_clarification.py`
- `tests/server/test_clues.py`
- `tests/server/test_objectives.py`
- `tests/server/test_player_intent.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_player_features.py`
- `tests/server/test_rag_router.py`
- `tests/server/test_rag_search.py`

**修改要求:**
- 所有 fixture 插入固定账号/剧本/房间时使用 `ON CONFLICT` 覆盖，或生成唯一 ID。
- 所有旧测试的 `client.post("/api/rooms", json={})` 改成：
  - 创建 host/admin account
  - 登录获取 token
  - 插入或创建 scenario
  - `POST /api/rooms` with `scenario_id` and Authorization
- RAG rule docs 测试既然现在要求登录，就补登录 token。
- `test_rag_search.py` 的 fake cursor 要适配 `RAGStore.search()` 先查询 room scenario 的行为，或把 scenario lookup mock 成独立 cursor。
- 不要为了让测试绿而降低真实鉴权规则。

**Verification:**
- Run: `python -m pytest tests/server/test_rooms.py -q`
- Run: `python -m pytest tests/server/test_room_security.py tests/server/test_host_room_lifecycle.py tests/server/test_rag_security.py -q`
- Run: `python -m pytest tests/server -q`
- Expected: 全部 PASS；若有外部依赖 skip，必须有明确 skip reason。
- Commit: `test: align legacy tests with authenticated flow`

---

## Task 8: 修前端剩余 localStorage 直读

**问题:** 计划要求统一 identity slot，但仍有页面绕过 `getSlotValue/setSlotValue`，尤其 admin 和 player logout。

**修改文件:**
- `src/client/src/pages/AdminDashboard.tsx`
- `src/client/src/pages/PlayerJoinPage.tsx`
- `src/client/src/components/IdentitySwitcher.tsx`
- 可保留 `src/client/src/shared/identity.ts` 和 `shared/platform.ts` 中的底层 localStorage 操作

**修改要求:**
- `AdminDashboard` 读取 token/account 改为 `getSlotValue`。
- 登出改为清理当前 slot 的 account 信息，而不是裸删全局 localStorage。
- `PlayerJoinPage` logout 同理。
- 允许 `identity.ts` 内部继续直接操作 localStorage。
- 允许 `platform.ts` 作为底层抽象继续使用 localStorage。

**Verification:**
- Run:

```powershell
rg "localStorage\.(getItem|setItem|removeItem)" src/client/src --glob "!**/shared/identity.ts" --glob "!**/shared/platform.ts"
```

- Expected: 只剩可解释的迁移代码；普通页面不再直接操作 token。
- Run: `cd src/client; node ./node_modules/typescript/bin/tsc --noEmit`
- Commit: `fix: complete identity slot usage`

---

## Task 9: 最终验证

**必须跑：**

```powershell
python -m pytest tests/server -q
cd src/client
node ./node_modules/typescript/bin/tsc --noEmit
node ./node_modules/vite/bin/vite.js build
```

**必须手动走一遍：**
1. 注册/登录 admin，确认可导入剧本。
2. 切换 host 身份，进入 `/host/create`，能看到剧本列表。
3. 选择剧本创建房间。
4. 进入 Host lobby，未加入玩家时不能普通开始。
5. 玩家登录，进入 `/player/join`，加入房间并 ready。
6. Host lobby 看到玩家状态，点击开始成功进入 stage。
7. Host stage WS 连接成功，HUD 有玩家。
8. 玩家提交行动，Host 收到叙事/日志，玩家收到行动完成。
9. Host reset/pause 不再 403。
10. 地图 tab 和日志 tab 仍然是不同 UI。

**最终交付说明必须包含：**
- 每个 Task 对应 commit hash。
- 完整测试结果。
- 如果仍有失败测试，列出文件、失败原因、为什么没有修。
- `git status --short` 输出。
- 是否有任何大文件或本地素材仍被跟踪。

## Assumptions

- 这轮不处理 STT、生产级 RBAC、完整地图编辑器、资料库高级 RAG 管理页。
- 这轮目标不是 UI 美化，而是把主流程和测试变成可信状态。
- 如果某个旧测试和新产品规则冲突，以新产品规则为准，但必须同步改测试，不允许直接删测试逃避覆盖。
