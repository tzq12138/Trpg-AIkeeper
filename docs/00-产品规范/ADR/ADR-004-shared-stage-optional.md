---
status: normative
version: 1.0
doc_owner: Product
effective_date: 2026-07-15
supersedes:
  - 第 4 项“Shared Stage 断线即暂停”的口径
depends_on:
  - docs/00-产品规范/01-运行模式、角色与权限总表.md
release_scope: M0
last_validated: 2026-07-15
---

# ADR-004：Shared Stage 永远可选

## 背景

公共大屏既被描述为运行端，也被描述为可选镜像。用其 ACK 决定行动完成会让设备故障改变业务事实。

## 决定

Shared Stage 是只读、party-safe、本地表现设备。它没有业务写权限，不能确认、拒绝或延迟状态提交。

## 后果

无 Stage 的两玩家路径必须可完整结束；Stage 断线只影响显示质量和重连，不暂停或回滚 Engine 已提交的事务。
