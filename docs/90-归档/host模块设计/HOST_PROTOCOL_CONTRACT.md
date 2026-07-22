# Host 协议契约 v2.0

本文是 Host 端 + Player 端通信协议的**单一事实源**。Python Engine、AI Tool Schema、React Host/Player 端类型定义必须以本文为准。

## v2.0 修订说明

1. **事件类型全集**：从 6 种扩展到 14 种，覆盖 Host 演出、Player 状态同步、动作生命周期、战术面板、抢占控制。
2. **统一信封 `EngineEvent`**：Host 和 Player 共用同一信封，通过 `audience` 和序列号字段区分。
3. **废弃声明**：`s2c_status_sync`、`s2c_roll_event`、`s2c_combat_state` 正式废弃。
4. **camelCase 强约束**：所有字段统一使用 camelCase。
5. **上行统一 REST**：Player 端所有写操作走 `POST /api/player/intent`。
6. **状态同步升级**：`s2c_full_snapshot` + `s2c_state_patch`（RFC 6902 JSON Patch）替代旧的 `s2c_status_sync`。

---

## 1. 权限边界

- **AI**：只能提出意图和结算请求，不能直接写入角色状态、物品、线索或场景进度。
- **Engine**：唯一状态写入者。所有 HP/SAN/物品/线索/场景变更必须由 Engine 生成、校验、落库并广播。
- **Host**：公共演出终端，只消费事件日志，不承载业务判定。
- **Player**：通过 `POST /api/player/intent` 提交玩家意图，不能直接修改权威状态，不能直接调用 AI 工具。

## 2. 统一下行信封 (`EngineEvent`)

所有 Engine → Client 消息使用统一信封：

```typescript
export interface EngineEvent<T = unknown> {
  eventId: string;           // 全局唯一 UUID，用于幂等去重
  roomId: string;
  type: EngineEventType;
  roomSequence: number;      // Engine 内部权威审计序号
  hostSequence?: number;     // Host 专属序列号 (audience='host' 时必填)
  playerSequence?: number;   // Player 专属序列号 (audience='player' 时必填)
  audience: EventAudience;   // 'host' | 'player' | 'party' | 'system'
  visibility: 'public' | 'private' | 'party' | 'hostOnly';
  transactionId?: string;    // txn_xxx（事务溯源）
  sourceActionId?: string;   // act_xxx（玩家动作溯源）
  issuedAt: number;          // 毫秒时间戳
  payload: T;
}

export type EventAudience = 'host' | 'player' | 'party' | 'system';
```

**铁律**：Engine 下发的信封禁止使用 `'broadcast'` 作为 `audience`。必须由 `ProjectionBuilder` 拆分为明确的 `host`、`player`、`party` 实例。

## 3. 全景事件类型枚举

```typescript
export type EngineEventType =
  // ─── 核心演出 ───
  | 's2c_reveal_transaction'   // 公共演出事务（掷骰、扣血、叙事、结果型氛围）
  | 's2c_chat_stream'          // 独立文本流（系统公告、无动作的纯对话）
  | 's2c_atmosphere'           // 环境型氛围切换（BGM、滤镜、震动）
  | 's2c_engine_state'         // Engine 状态指示（"守秘人正在思考"）
  | 's2c_scene_sync'           // 场景背景图同步

  // ─── Player 端状态同步 ───
  | 's2c_full_snapshot'        // 全量状态快照（重连、初始化时下发）
  | 's2c_state_patch'          // 增量状态补丁（RFC 6902 JSON Patch）
  | 's2c_private_notice'       // 私密通知（获得私密物品/线索/暗骰结果）
  | 's2c_public_observation'   // 旁观视角的模糊观察（"XX脸色惨白"）

  // ─── 动作生命周期 ───
  | 's2c_action_completed'     // 意图彻底结算完毕（解锁 UI）

  // ─── 抢占控制 ───
  | 's2c_resume_transaction'   // 恢复被中断的事务
  | 's2c_cancel_transaction'   // 取消被中断的事务

  // ─── Player 战术面板 ───
  | 's2c_tactical_prompt';     // AI 战术选项下发

// ─── 废弃事件 ───
// ❌ s2c_status_sync  → 迁移至 s2c_full_snapshot + s2c_state_patch
// ❌ s2c_roll_event    → 迁移至 s2c_reveal_transaction.steps[].kind='roll'
// ❌ s2c_combat_state  → 未定义幽灵事件，正式废弃
```

## 4. 防剧透事务 (`s2c_reveal_transaction`)

```typescript
export interface RevealTransactionPayload {
  transactionId: string;
  priority: 'normal' | 'urgent';
  steps: RevealStep[];
}

export type RevealStep =
  | { kind: 'roll'; payload: RollEventPayload }
  | { kind: 'status_delta'; payload: StatusDeltaStepPayload }
  | { kind: 'scene_transition'; payload: SceneSyncPayload }
  | { kind: 'narrative_text'; payload: NarrativeTextPayload };
```

Host 端 `TransactionPlayer` 必须按 `steps` 顺序执行：
1. `roll` → 3D 骰子动画
2. `status_delta` → 公共状态变更 + HUD 动画
3. `scene_transition` → 背景切换
4. `narrative_text` → 打字机字幕

**Urgent 抢占规则**：`priority: 'urgent'` 的事务到达时，当前 Normal 事务被中断（`interruptActiveTransaction`），Urgent 事务插队播放。Engine 在 Urgent 结束后下发 `s2c_resume_transaction` 或 `s2c_cancel_transaction`。

## 5. 掷骰与状态变更 Payload

```typescript
export interface RollEventPayload {
  rollId: string;
  characterId: string;
  skillName: string;
  diceType: string;
  rolledValue: number;
  targetValue: number;
  resultType: 'critical_success' | 'extreme_success' | 'hard_success' | 'regular_success' | 'failure' | 'fumble';
  label: string;
  timeoutMs?: number;  // 动画超时（ms），默认 15000
}

export interface StatusDeltaStepPayload {
  characterId: string;
  publicDelta: {
    hp?: { before: number; after: number; max: number };
    san?: { before: number; after: number; max: number };
    mp?: { before: number; after: number; max: number };
    luck?: { before: number; after: number; max: number };
    tagsAdded?: string[];
    tagsRemoved?: string[];
  };
  displayMode: 'exact' | 'vague';
  durationMs?: number;  // 动画时长（ms），默认 1500
}
```

## 6. 流式文本 Payload

```typescript
export interface NarrativeTextPayload {
  role: 'keeper' | 'npc' | 'system';
  speakerName?: string;
  text: string;           // MVP 阶段统一下发完整文本
  blocking?: boolean;     // 若 true，等待打字机播放完毕再推进 step
}
```

## 7. 氛围协议 Payload

```typescript
export interface AtmospherePayload {
  visual?: {
    filter?: 'deep_red' | 'cold_blue' | 'sepia' | 'darkness';
    vignette?: number;
    shake?: { intensity: 'low' | 'medium' | 'high'; durationMs: number };
    glitch?: boolean;
  };
  bgm?: {
    trackId: string | null;
    volume: number;
    fadeInMs: number;
  };
  sfx?: Array<{ clipId: string; volume?: number }>;
}
```

字段统一使用 camelCase。废弃写法 `track` / `fade_in` / `shake.duration`。

## 8. 状态同步 Payload

```typescript
// 全量快照
export interface FullSnapshotPayload {
  stateVersion: number;
  character: CharacterNode;
  inventory: Item[];
  clues: ClueNode[];
  currentSceneImageUrl?: string;
}

// 增量补丁（RFC 6902）
export interface StatePatchPayload {
  baseStateVersion: number;   // 必须与前端当前版本一致
  nextStateVersion: number;   // 应用后的新版本号
  characterId: string;
  patches: JsonPatchOperation[];
  inventory?: Item[];         // 全量替换（如果物品变更）
  clues?: ClueNode[];         // 全量替换（如果线索变更）
}

export type JsonPatchOperation =
  | { op: 'replace'; path: string; value: unknown }
  | { op: 'add'; path: string; value: unknown }
  | { op: 'remove'; path: string };
```

## 9. 动作生命周期 Payload

```typescript
export interface ActionCompletedPayload {
  actionId: string;
  transactionId?: string;
  status: 'resolved' | 'rejected' | 'expired' | 'cancelled' | 'timeout';
  reasonCode?: string;
  message?: string;
  nextStateVersion?: number;
}
```

## 10. 战术面板与公共观察 Payload

```typescript
export interface TacticalPromptPayload {
  text: string;
  actions: Array<{
    actionId: string;
    label: string;
    intentType: string;
    params: Record<string, any>;
  }>;
}

export interface PublicObservationPayload {
  characterId: string;
  observationText: string;
}
```

## 11. 中断/恢复/取消 Payload

```typescript
export interface ResumeTransactionPayload {
  transactionId: string;
}

export interface CancelTransactionPayload {
  transactionId: string;
  summaryText?: string;
  reasonCode?: string;
}
```

## 12. 上行意图接口（Player → Engine）

所有 Player 端写操作统一走 REST API：

**`POST /api/player/intent`**

```typescript
// 请求体 — characterId 由服务端从 X-Room-Token 解密，前端不传
{
  actionId: string;          // 前端生成的 UUID，用于幂等去重
  intentType: 'skill_check' | 'use_item' | 'show_item' | 'voice_command' | 'dialogue' | 'move';
  declaredIntent: string;    // 自然语言描述
  baseStateVersion: number;  // 当前本地状态版本，Engine 校验防并发
  params?: Record<string, any>;
}

// 响应
// HTTP 202: { status: 'queued', actionId, message: '意图已受理' }
// HTTP 409: { status: 'conflict', error: '状态已过期' }
// HTTP 429: { status: 'rate_limited', error: '请求过于频繁' }
```

## 13. 规则映射格式

规则文件使用 JSON5 或受限 DSL，不使用可执行 Python 表达式。`condition` 必须由白名单算子组成。COC 奖惩骰、孤注一掷、幸运改判等系统特性由 `rulePluginHandlers` 注册。
