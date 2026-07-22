# 《向火独行》M0：MIMO Narrator 修复记录

**日期：** 2026-07-15  
**范围：** 最小 MCP 契约、MIMO 叙事结果兼容，以及单人房间的首个自然语言行动。  
**停止点：** 用户要求修复当前阻塞后暂停；本记录不把完整通关误报为已完成。

## 已修复的问题

MIMO 的 OpenAI 兼容接口会稳定返回可解析 JSON，但其 Narrator 输出存在三种合法语义、但不完全符合本地严格 DTO 的形状：

1. 使用 `success` 代替契约规定的 `completed`；
2. 将四个展示字段的 citation 合并为单个 `fact_refs` 列表；
3. 偶尔省略 `interactable_objects` 与 `open_question`。

网关现在仅在所有引用均属于当前 `allowed_facts` 时，才把扁平引用列表展开为字段级引用，并将 `success` 归一化为 `completed`。缺失对象只会从已验证的场景对象回填；若编译包没有对象，则显示受 `fact:scene-*` 约束的“当前环境”。缺失追问只会基于该同一可验证对象或场景生成。不会补写状态、隐藏事实、分支、骰点或未验证 citation。

## 浏览器复现

- 新建房间：`407289be`，剧本为《向火独行》；
- 角色：剧本预设“查尔斯·钱伯斯”；角色卡展示 HP `11/11`、SAN `50/50`；
- 入房预检：REST、WebSocket 和延迟均正常；Session Zero 的五项确认均完成；
- 玩家自然语言行动：
  > 我提起行李箱，上那辆开往阿卡姆的长途车；上车前留意周围乘客的反应。
- 临时理解与正式预览均正确识别为中风险 `movement` / `state_change`，无技能检定，置信度分别为 `95%` / `90%`。

该房间的确认行动发生在最终兼容修复加载之前，因此保留为 `awaiting_host_exception` 以维持事件可追溯性；没有篡改或重放旧行动。它也证明此前错误并非移动裁决失败：权威场景已推进，但 Narrator 的返回被严格契约拒绝。

## 最终真实 MIMO 验证

对上述行动的同一份权威 Narrator 上下文进行了不写状态的真实调用。活动的管理员加密配置被选为主提供商，结果为：

- `accepted: true`
- `status: completed`
- `provider_source: configured_provider`
- citation 字段完整：`narrative_text`、`environment_changes`、`interactable_objects`、`open_question`
- 至少一个环境变化、一个可交互对象，以及一个开放追问

整个过程没有输出、记录或写入 API Key、密文或上游原始响应。

## 自动化验证

```text
python -m pytest tests/server/test_ai_gateway.py \
  tests/server/test_narrator_runtime.py \
  tests/server/test_kp_mcp_brain.py \
  tests/server/test_ai_providers.py \
  tests/server/test_solo_adventure_runtime.py \
  tests/server/test_kp_mcp_config.py \
  tests/server/test_director_runtime.py -q

79 passed, 4 existing Pydantic serialization warnings

git diff --check
# 通过；仅有工作树既存的 CRLF 提示
```

## 本轮未做

- 未重放修复前的异常行动；旧回执保持可审计状态；
- 未进行新的完整单人通关，因此调查、战斗、理智、结局和重连的浏览器验收仍待下一轮；
- 未改变 RAG embedding、CoC7 状态执行或已发布剧本内容。
