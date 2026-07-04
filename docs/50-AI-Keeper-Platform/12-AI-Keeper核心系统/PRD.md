# AI-Keeper 核心系统 PRD 初版

## 目标

让 AI 在安全边界内主持跑团：能叙事、建议检定、组织上下文和控制节奏，但不能直接写状态、泄露真相或把猜测变事实。

## 范围

包含 soul、Prompt 编排、RAG、上下文压缩、输出 schema 校验、反幻觉、真相锁定、provider fallback 和 AI 调用审计。不包含多模型商业调度、自动生成地图和完整 AI 角色群。

## 角色

| 角色 | 权限 |
|---|---|
| AI KP | 生成叙事、建议检定、建议状态变更。 |
| Engine | 校验 AI 输出并写权威状态。 |
| 玩家 | 接收授权叙事和反馈。 |
| 房主 | 查看有限诊断和恢复信息。 |

## 用户故事

| 编号 | 用户故事 | 优先级 |
|---|---|---:|
| AI-1 | 作为玩家，我能收到稳定风格的 AI KP 叙事。 | P0 |
| AI-2 | 作为系统，我能阻止 AI 直接改状态。 | P0 |
| AI-3 | 作为系统，我能阻止 AI 泄露未发现线索。 | P0 |
| AI-4 | 作为开发者，我能诊断 AI provider 失败。 | P1 |

## 数据边界

AI 输入由房间状态、角色状态、已授权知识、近期事件和任务指令组成。AI 输出分为 narrative、roll request、state suggestion、tactical prompt、keeper note 和 citation。任何状态建议必须由 Engine 校验。

## 接口 / 事件方向

- Gateway：`resolve_turn`、`compile_mechanic`、`structure_scenario`、`query_rules`、`query_knowledge`。
- Event：`ai_call_started`、`ai_call_finished`、`ai_output_rejected`、`ai_fallback_used`。
- Provider：DeepSeek、MCP、Local fallback 按配置顺序调用。

## 验收标准

- AI 输出 schema 无效时不会落库。
- 未发现线索不进入 Player 投影。
- AI 不能直接扣 HP/SAN 或增删物品。
- provider 失败有可读 fallback 和日志。

