# AI-Only v1.1 门禁阶段报告

日期：2026-08-20  
状态：P0 进行中；未执行 Golden Run，不代表纯 AI 模式发布通过。

## 本轮完成

- `AI_ONLY_ACCEPTANCE_SPEC.md` 升级为草案 v1.1：修正 RiskContract/ActionConsent 边界，拆分 action、room runtime、resolution outcome 三层状态，明确 Room Owner/Stage Client/Legacy Host Adjudicator，补充 Host API gates、Session Zero、重试不变量、ProviderFailure、Trace、运行包条件门禁、指标分母/样本及追踪矩阵。
- `ai_only` Host review、recalculate、exception 入口统一返回 `409 AI_ONLY_HOST_ADJUDICATION_DISABLED`；turn skip 入口同样拒绝，避免通过缺席处理 API 变成人工裁决。
- `AiGateway` 增加结构化 `ProviderFailure(task_type, attempts, last_error_code, fallback_available)`；Provider 与本地降级全部失败时不再返回空字典、空 `NarrativePayload` 或空 `KpResponse`。未登记的本地降级任务也 fail-closed。
- action state 增加独立的 `ROOM_RUNTIME_STATUSES` 与 `RESOLUTION_OUTCOMES` 注册表和校验函数，保持历史 `ACTION_STATUSES` 兼容。
- P0-4 Glass Rain 运行时字段与严格编译门禁已落地；P0-6A Trace 已接入隔离 Golden Suite，管理员具备有界脱敏查询；P0-6B 已建立指标聚合器与 30 场样本门槛。

## 验证证据

```text
python -m pytest tests/server/test_host_autonomy.py \
  tests/server/test_action_reviews_v2.py \
  tests/server/test_action_drafts_v2.py \
  tests/server/test_ai_gateway.py \
  tests/server/test_room_provider_health.py -q
131 passed, 1 warning (Starlette/httpx TestClient 弃用警告)

python -m pytest tests/server/test_action_state_machine_v2.py \
  tests/server/test_ai_gateway.py::test_all_provider_failures_return_structured_failure_without_empty_dto \
  tests/server/test_action_reviews_v2.py::test_ai_only_player_review_does_not_enqueue_host_review \
  tests/server/test_action_reviews_v2.py::test_ai_only_host_skip_character_is_not_a_manual_adjudication_path -q
37 passed, 1 warning

python -m compileall -q <受控后端文件>
通过

git diff --check
退出码 0（Git 仅提示工作区已有 LF/CRLF 转换告警）
```

## 尚未完成/不可宣称

- 自动申诉循环（原始意图 → 重新解释 → 原 `RollReceipt` 复核 → 规则重算 → upheld/corrected/compensated）尚未接入；当前纯 AI 申诉仍 fail-closed，不进入 Host 队列。
- 隔离 Golden Suite 已完成 9/9 样本，Trace complete=9/9、Host 裁决=0；这不是 Glass Rain 真实浏览器多人验收，也不等于 30 场双人/四人 benchmark 已执行。
- Provider 故障/Host 离线/恶意提示注入/并发重试/hash freeze 的整场 Golden 矩阵和真实浏览器验证仍未执行。
- 本轮未修改 `CLAUDE.md` 及用户已有文档/未跟踪文件；未提交、未合并、未推送。
