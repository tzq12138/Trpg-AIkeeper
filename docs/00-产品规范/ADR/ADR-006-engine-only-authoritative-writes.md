---
status: normative
version: 1.0
doc_owner: Architecture
effective_date: 2026-07-15
supersedes:
  - “AI 主导部分世界状态”的宽泛口径
depends_on:
  - docs/00-产品规范/03-领域对象与唯一权威矩阵.md
release_scope: M0
last_validated: 2026-07-15
---

# ADR-006：Engine 是唯一权威状态写入者

## 背景

如果 AI 叙事、前端投影或房主操作可直接改变状态，骰子、公平性、恢复和剧透隔离无法验证。

## 决定

Player 提供输入，AIKeeper 提供理解/叙事建议，Rule Executor 产生规则结果；只有 Engine 能验证前置条件、提交状态、写事件并生成投影。

## 后果

规则结果先于叙事；所有变更关联 `ResolutionTransaction`。AI 输出冲突或失败时进入澄清/降级/异常链，而不是绕过提交。
