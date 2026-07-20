---
status: normative
version: 1.0
doc_owner: Product
effective_date: 2026-07-15
supersedes: []
depends_on:
  - docs/00-产品规范/03-领域对象与唯一权威矩阵.md
release_scope: M0
last_validated: 2026-07-15
---

# ADR-002：使用人工验证的参考短模组

## 背景

任意 PDF、扫描件和多模态导入的质量不稳定，不能作为可信主链的前置假设。

## 选项

1. 任意文档自动开团；2. 仅人工维护内容；3. 发布前校验的参考短模组。

## 决定

M0 选择第三项：引用来源、结构化世界书、规则绑定、素材和质量报告均在开团前固定为 `ScenarioVersion`。

## 后果

自动导入可以继续演进，但必须先生成草稿和异常报告；未通过发布门禁的版本不可成为 M0 黄金路径。
