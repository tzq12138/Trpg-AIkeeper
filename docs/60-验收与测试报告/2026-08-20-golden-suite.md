# 六类黄金样本批量导入与通关报告

- 模组目录：9
- 已完成房间：9
- 执行模式：隔离 PostgreSQL 测试库 + 确定性结构化/规则夹具 + 正式 FastAPI 路由。
- 素材包结局标为 `derived_from_materials_only`，不主张为原文结局。

## 结果

| 模组 | 导入 | 运行包 | 动作 | 房间 | Trace | Host 裁决 | 结局来源 |
| --- | --- | --- | --- | --- | --- | ---: | --- |
| cn-into-the-flames | draft_ready | ready | completed | completed | complete | 0 | source_backed (向火独行.pdf#page:2) |
| cn-neon-gods | draft_ready | ready | completed | completed | complete | 0 | source_backed (COC7扩展-众神的霓虹.docx#paragraph:1) |
| cn-scarlet-document | draft_ready | ready | completed | completed | complete | 0 | source_backed (猩红文档.pdf#page:1) |
| cn-the-dark-box | draft_ready | ready | completed | completed | complete | 0 | source_backed (常暗之厢（7版规则，简体修正版）.doc#page:1) |
| en-alone-against-the-flames | draft_ready | ready | completed | completed | complete | 0 | source_backed (01_Alone_Against_the_Flames_EN.pdf#page:2) |
| en-doors-to-darkness | draft_ready | ready | completed | completed | complete | 0 | derived_from_materials_only (11_Doors_to_Darkness_Handouts.pdf#page:1) |
| en-gateways-to-terror | draft_ready | ready | completed | completed | complete | 0 | derived_from_materials_only (09_Gateways_to_Terror_Handouts.pdf#page:1) |
| en-lightless-beacon | draft_ready | ready | completed | completed | complete | 0 | source_backed (08_The_Lightless_Beacon_EN.pdf#page:1) |
| en-mansions-of-madness | draft_ready | ready | completed | completed | complete | 0 | derived_from_materials_only (Mansions of Madness Handouts Pack Itchio.pdf#page:1) |

## 规则书与角色卡

- 规则书通过正式 `/api/rag` 接口写入隔离的版本化规则集；使用确定性分片夹具验证持久化链，不代表真实 embedding 召回质量。
- 已发布规则版本：`464bccc9-12ea-4ea9-a49d-2c7e5dd8e5ff`

| 规则书 | 文本字符 | 分片 | 状态 |
| --- | ---: | ---: | --- |
| 02_QuickStart_Rules_EN.pdf | 108277 | 217 | indexed |
| 05_守秘人规则书_中文v2002c.pdf | 546740 | 1094 | indexed |
| 06_调查员手册_中文v1.2.1.pdf | 170870 | 342 | indexed |
| 07_Starter_Set_中文版.pdf | 27503 | 56 | indexed |
| COC7th核心规则书v1.2.1.pdf | 517341 | 1035 | indexed |
| COC七版基础规则.pdf | 27503 | 56 | indexed |
| 克苏鲁的呼唤第七版守秘人规则书Version2002c.pdf | 546740 | 1094 | indexed |
| 克苏鲁的呼唤第七版调查员手册1.21.pdf | 243307 | 487 | indexed |
| 快速入门手册-基础规则.pdf | 27503 | 56 | indexed |

| 角色卡素材 | 类型 | 状态 | 详情 |
| --- | --- | --- | --- |
| 03_Character_Sheet_7thEd_EN.pdf | PDF | parsed | parts=2, multimodal=False |
| COC七版规则空白卡CY20.02.1.xlsx | XLSX | previewed | skills=67 |
