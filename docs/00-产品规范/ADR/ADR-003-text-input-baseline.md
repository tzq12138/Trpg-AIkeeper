---
status: normative
version: 1.0
doc_owner: Product
effective_date: 2026-07-15
supersedes: []
depends_on:
  - docs/00-产品规范/02-核心用户旅程与生命周期.md
release_scope: M0
last_validated: 2026-07-15
---

# ADR-003：文字输入是 M0 唯一验收基线

## 背景

语音转写、按住说话和多媒体可以改善体验，但如果拥有独立的确认、权限或状态路径，会破坏可解释性和恢复性。

## 决定

M0 的权威输入契约以文字为准。语音若存在，只能转换为用户可编辑、可确认的文字，不得绕过 Intent Contract、风险确认或审计。

## 后果

核心可访问性、弱网和测试均以文字主链为基准；语音质量、实时性和语音特有风险不作为 M0 阻塞项。
