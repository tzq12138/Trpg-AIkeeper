---
status: normative
version: 1.0
doc_owner: Product
effective_date: 2026-07-15
supersedes:
  - 以 Host 同时表示房主、主持人和大屏设备的口径
depends_on:
  - docs/00-产品规范/01-运行模式、角色与权限总表.md
release_scope: M0
last_validated: 2026-07-15
---

# ADR-005：拆分人、设备和服务角色

## 背景

单一 Host 概念会把房间管理、真相访问、大屏播放和剧情裁决错误地合并。

## 决定

规范只使用 ScenarioPreparer、RoomOwner、TableSteward、Player、SharedStage、AIKeeper 和 Engine。一个人可兼任多个“人”角色，但凭证、权限与审计主体分离。

## 后果

旧代码的 Host 只可作为兼容名。任何 API 或 UI 都必须说明其对应的规范角色，不能从名称推导真相或写入权限。
