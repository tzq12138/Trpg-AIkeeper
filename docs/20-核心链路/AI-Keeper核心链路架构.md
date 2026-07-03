# AI-Keeper 核心链路架构

## 核心链路

AI-Keeper 的护城河不是“AI 会写旁白”，而是系统能让 AI 在安全边界内驱动一个有状态世界。

```text
Player Intent
  -> Intent Gateway
  -> Mechanic Compiler / AI KP Suggestion
  -> Rule Executor
  -> Engine Transaction
  -> Authoritative State Mutation
  -> Projection Builder
  -> Host / Player / Party Events
  -> Event Log / Archive
```

## 角色边界

| 角色 | 可以做 | 不可以做 |
|---|---|---|
| Player | 提交意图、查看自己的角色/线索/回执、主动分享私密线索。 | 直接写状态、伪造角色身份、读取未授权真相。 |
| Host | 展示公共舞台、接收公共事件、执行暂停/重试/有限急救。 | 承载规则裁决、查看完整 KP-only 真相、绕过 Engine 改状态。 |
| AI KP | 生成叙事、检定建议、状态建议、线索建议、战术提示。 | 直接落库、直接扣 HP/SAN、把玩家猜测写成事实。 |
| Engine | 校验意图、执行规则、写权威状态、拆分投影、记录日志。 | 生成不受校验的自由叙事。 |

## 数据原则

| 原则 | 说明 |
|---|---|
| Engine 唯一写入口 | HP、SAN、物品、线索、场景、行动状态只能由 Engine 校验后写入。 |
| AI 输出先校验 | AI 输出必须经过 schema、权限、真相、规则和状态边界校验。 |
| 玩家身份以 token 为准 | Player 请求不能信任前端传来的 `characterId` 作为安全身份。 |
| Host 只消费事件 | Host 不做规则判定，不根据 UI 状态推导世界事实。 |
| 私密信息最小投影 | 私密线索只投给拥有者，团队版本必须是 Engine 生成的公开摘要。 |
| 日志是可追溯事实 | 每个权威变更都要能从事件日志查到来源行动和事务。 |

## 四阶段裁决

| 阶段 | 执行者 | 目标 | 失败处理 |
|---|---|---|---|
| 资产校验 | Python / Engine | 校验玩家是否拥有物品、目标是否存在、场景是否允许。 | 直接拒绝并解锁 UI，不消耗 AI。 |
| 机制编译 | LLM 或本地 fallback | 把自由文本编译为 `skill_check`、`dialogue`、`retroactive_item_claim` 等机制。 | 归一化失败后降级本地规则或返回可解释错误。 |
| 规则执行 | Python RuleExecutor | 掷骰、计算成功等级、扣 HP/SAN、生成权威事实。 | 保留失败事实，不能让 AI 改写数学结果。 |
| 叙事渲染 | AI KP / Narrative Provider | 根据权威事实生成 Host/Player 可见文本和提示。 | AI 不可用时用可读 fallback，不返回空白。 |

## 必补状态机风险

| 风险 | 表现 | 修复口径 |
|---|---|---|
| 事实时差 | 规则已判定昏迷，AI 叙事还写“站起来继续跑”。 | 叙事上下文必须注入级联状态后果。 |
| 剧透穿透 | 私密 patch 早于 Host 公共演出到达。 | 私密 patch 支持 `executeAfter` 或事务节点完成后再下发。 |
| 幽灵补丁 | 重连时 snapshot 与 patch 乱序覆盖。 | Player 实现 state version barrier 和 patch buffer。 |
| 抢占残留 | Urgent 事务插队但 BGM/旧演出状态未挂起。 | Host 事务播放器联动音频/演出资源挂起与恢复。 |

## DeepSeek 实现红线

- 不允许为了快速修 UI 绕过后端权限。
- 不允许让 AI 直接返回数据库写入命令。
- 不允许把未发现线索、模组真相、KP-only prompt 放入 Player 可见上下文。
- 不允许用前端本地状态作为权威状态来源。
- 不允许在没有测试的情况下重构核心链路。
