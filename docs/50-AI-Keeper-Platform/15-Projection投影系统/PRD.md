# Projection 投影系统 PRD 初版

## 目标

建立统一投影层，把权威事件和状态变化安全拆分给不同受众，避免私密信息泄露、乱序覆盖和 Host 视角越权。

## 范围

包含 audience、事件信封、Host/Player/Party/KP 投影、版本屏障、patch buffer、投影时序和重连恢复。不包含高级数据订阅 DSL 和完整审计后台。

## 角色

| 角色 | 权限 |
|---|---|
| Host | 接收公共舞台投影。 |
| Player | 接收个人和团队授权投影。 |
| AI KP | 接收受控上下文，不接收 Player UI payload。 |
| Observer | 接收公共只读投影。 |

## 用户故事

| 编号 | 用户故事 | 优先级 |
|---|---|---:|
| PROJ-1 | 作为玩家，我只会收到自己能知道的信息。 | P0 |
| PROJ-2 | 作为房主，我能看到公共舞台而不是完整剧透视角。 | P0 |
| PROJ-3 | 作为系统，我能处理重连时 snapshot 和 patch 乱序。 | P0 |
| PROJ-4 | 作为系统，我能延迟私密反馈直到公共演出完成。 | P0 |

## 数据边界

投影 payload 是视图，不是权威状态。每个 payload 带 audience、targetUser/character、roomSequence、stateVersion、transactionId 和 visibility reason。

## 接口 / 事件方向

- Internal：ProjectionBuilder 输入权威事件，输出受众 payload。
- WS：Host/Player/Observer 分别订阅对应投影。
- Event：`projection_created`、`projection_delivered`、`projection_blocked`、`projection_replayed`。

## 验收标准

- 未授权字段不出现在响应 JSON 中。
- Host 投影不含 KP-only 真相。
- 重连时版本旧 patch 不覆盖新 snapshot。
- 私密反馈不早于公共演出节点。

