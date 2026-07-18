---
status: normative
version: 1.0
doc_owner: Product
effective_date: 2026-07-15
supersedes: []
depends_on:
  - docs/00-产品规范/00-产品宪法.md
release_scope: M0
last_validated: 2026-07-15
---

# ADR-001：M0 只支持 AI-only

## 背景

产品曾同时出现“AI 独立 KP”“房主复核剧情”和“AI 辅助真人 KP”三种叙述，导致真相访问和状态权威无法成立。

## 选项

1. AI-only；2. Human Keeper；3. 两种模式并行。

## 决定

M0 选择 AI-only。AIKeeper 不是状态权威，RoomOwner 不是剧情裁判，TableSteward 只处理安全和操作恢复。

## 后果

M0 不建设真人 KP 工作台或运行期剧情复核队列。Human Keeper 必须以独立运行模式和新 ADR 引入。
