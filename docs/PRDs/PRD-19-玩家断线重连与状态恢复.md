# PRD-19 - 玩家断线重连与状态恢复

**版本**: 1.0  
**状态**: 待开发  
**定位**: 手机刷新、弱网和断线后的恢复体验

## 1. 背景

手机端容易锁屏、切后台、刷新或断网。AI 自动 KP 不能因为某个玩家断线就丢失私密线索、行动状态或 ready 状态。Player 端需要明确的重连和快照恢复策略。

## 2. 目标

- 保留本地 room token 和最后序列号。
- 重连后恢复角色、线索、行动回执、未读通知。
- 网络异常时给玩家明确状态。
- 避免重复提交或重复应用事件。

## 3. 范围边界

**包含**: WebSocket 重连、快照重拉、未读提示恢复、pending action 恢复。  
**不包含**: 多设备同时登录冲突、离线行动提交。

## 4. 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-19-1 | 作为玩家，我刷新手机后能回到自己的角色。 | P0 |
| US-19-2 | 作为玩家，断线期间我想知道当前不能提交行动。 | P0 |
| US-19-3 | 作为玩家，我不想因为重连重复收到同一条私密线索。 | P0 |

## 5. 功能需求

1. 本地保存 `roomToken`、`roomId`、`lastPlayerSequence`。
2. WebSocket 重连携带 lastSequence。
3. 序列断档或 patch 版本冲突时调用 `/api/player/sync`。
4. 网络断开时行动入口置灰，显示重连状态。
5. pending action 重连后通过 action status 查询恢复。
6. 未读私密通知和战术 prompt 从快照恢复。
7. 重复 eventId 必须幂等丢弃。

## 6. 接口/事件依赖

| 类型 | 名称 | 用途 |
|---|---|---|
| WebSocket | `lastSequence` | 增量续传 |
| REST | `GET /api/player/sync` | 全量恢复 |
| REST | `GET /api/player/actions/:actionId` | pending action 查询 |
| Event | `s2c_full_snapshot` | 恢复状态 |
| Store | `lastPlayerSequence` | 去重 |

## 7. 状态与错误处理

- token 失效时回到加入房间页。
- sync 失败时保留本地只读状态并提示重试。
- pending action 超时后显示可重新提交。
- 长时间离线后重连需要拉全量快照。

## 8. 验收标准

- 手机刷新后恢复角色和线索。
- 断线期间不能重复提交行动。
- 重连不重复应用旧事件。
- patch 冲突能自动转全量同步。

## 9. 测试场景

1. 玩家收到线索后刷新，线索仍存在。
2. WebSocket 断开，行动按钮置灰。
3. 重连收到重复事件，被丢弃。
4. patch 版本冲突，触发 sync。

## 10. 风险依赖

- 依赖服务端保留足够事件或快照。
- 多设备同角色后续需要单独设计。
- 手机后台限制可能导致 WebSocket 长时间断开。

## 11. 已知架构 Bug：断线重连时的幽灵补丁 (Ghost Patch)

**来源**：`数据流bug+思考.md` Bug 3

**场景**：
1. 玩家手机断网 5 秒，期间 Engine 下发毒气伤害 `s2c_state_patch`（`baseVersion=105 → 106`）。
2. 手机重连，因序列号落后主动请求 `GET /api/player/sync`。
3. 全量快照在 HTTP 传输中，WebSocket 同时重传了 Patch。
4. 前端先应用 Patch（基于旧版本），再被 Snapshot 全量覆盖 → 版本号不可逆错乱。

**防御方案：State Version Barrier（状态版本屏障）**

Player Store 的 `applyStatePatch` 方法必须实现以下逻辑：

1. 收到 `s2c_state_patch` 时，检查 `baseStateVersion`：
   - 若 `base === currentVersion`：正常应用，递增 `currentVersion`。
   - 若 `base > currentVersion`（出现断层）：将 Patch 压入 `pendingPatches` 缓冲区，**不应用**。
2. 断层出现时，立即拉取 `GET /api/player/sync`。
3. 全量快照到达并应用后，丢弃所有 `baseStateVersion <= snapshot.stateVersion` 的缓存 Patch。
4. 若仍有 `baseStateVersion > snapshot.stateVersion` 的 Patch，按序应用。

**伪代码**：
```typescript
function applyStatePatch(patch: StatePatchPayload) {
  if (patch.baseStateVersion === currentVersion) {
    applyPatch(patch.patches);
    currentVersion = patch.nextStateVersion;
  } else if (patch.baseStateVersion > currentVersion) {
    pendingPatches.push(patch);
    if (!syncInProgress) {
      syncInProgress = true;
      fetchFullSnapshot(); // GET /api/player/sync
    }
  }
  // baseStateVersion < currentVersion → 丢弃（过期 Patch）
}

function onFullSnapshot(snapshot: FullSnapshot) {
  applySnapshot(snapshot);
  currentVersion = snapshot.stateVersion;
  pendingPatches = pendingPatches.filter(p => p.baseStateVersion > currentVersion);
  pendingPatches.sort((a, b) => a.baseStateVersion - b.baseStateVersion);
  for (const p of pendingPatches) applyStatePatch(p);
  syncInProgress = false;
}
```

**新增测试场景**：
5. 断网期间收到 Patch → 重连后 Patch 进入缓冲区 → Snapshot 到达后缓冲区清空 → 无版本错乱。
6. 连续 3 个 Patch（105→106, 106→107, 107→108）到达但 currentVersion=104 → 全部缓冲 → Snapshot(108) 到达后按序应用。

