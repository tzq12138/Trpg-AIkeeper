---
status: normative
version: 1.0
doc_owner: Product
effective_date: 2026-07-15
supersedes: []
depends_on:
  - docs/90-归档/方向性问题头脑风暴/README.md
release_scope: M0
last_validated: 2026-07-15
---

# 06：决策记录 ADR

本页是 M0 重大取舍的索引，而不是重复产品规范。每个 ADR 必须包含背景、可选方案、决定、影响、非目标和被替代口径；其状态高于历史材料和模块 PRD。

## M0 固定决策

| ADR | 决定 | 主要来源 | 影响 |
|---|---|---|---|
| [ADR-001](./ADR/ADR-001-ai-only-m0.md) | M0 只支持 `ai_only` | M0 总计划；第 1 问 | 不建设 Human Keeper 剧情裁决后台 |
| [ADR-002](./ADR/ADR-002-verified-reference-module.md) | M0 使用人工验证的参考短模组 | M0 总计划；第 13–16 问 | PDF 自动导入不作为验收前提 |
| [ADR-003](./ADR/ADR-003-text-input-baseline.md) | 文字是唯一验收基线 | M0 总计划；第 130–136 问 | 语音只能是输入适配器 |
| [ADR-004](./ADR/ADR-004-shared-stage-optional.md) | Shared Stage 永远可选 | M0 总计划；第 3–4 问 | Stage ACK 不阻塞权威行动 |
| [ADR-005](./ADR/ADR-005-separate-roles-devices-services.md) | 人、设备、服务角色拆分 | M0 总计划；第 2、5–9 问 | `Host` 不再是规范角色 |
| [ADR-006](./ADR/ADR-006-engine-only-authoritative-writes.md) | Engine 唯一权威写入 | M0 总计划；第 21–26、29 问 | AI/Player/Stage 不能直接写状态 |
| [ADR-007](./ADR/ADR-007-no-runtime-ai-canon.md) | M0 禁止 AI 运行时创造新 Canon | M0 总计划；第 10–11、17–25 问 | AI 受已发布版本和 Engine 约束 |
| [ADR-008](./ADR/ADR-008-trusted-short-module-not-campaign.md) | M0 是可信短团，不是长期战役 | M0 总计划；第 7、77–79、96–105 问 | Campaign 治理和部署迁移后置 |

## 历史裁决映射

[裁决映射](./ADR/裁决映射.md) 覆盖第 1–200 问，给出每一段的有效状态：

- `adopted`：已被本规范直接吸收；
- `amended`：保留目标，但具体口径被 M0 ADR 修正；
- `archived`：仅保留历史背景，不是 M0 当前规则；
- `later`：方向有效但不进入 M0 验收或实现承诺。

当历史文本与 ADR 或规范冲突时，必须以 ADR/规范为准，并在新的设计文档中引用映射项。
