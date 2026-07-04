# Module 模组编辑器 PRD 初版

## 目标

让创作者或房主能把剧本资料整理成 AI-Keeper 可主持的结构化模组，并一键创建可运行房间。

## 范围

包含剧本基础信息、PDF 导入、结构化、真相、开场、NPC、地点、线索、隐藏信息、质量报告和一键开局。不包含社区发布市场和多人协作编辑。

## 角色

| 角色 | 权限 |
|---|---|
| 创作者 | 创建和编辑模组。 |
| 房主 | 选择模组并创建房间。 |
| AI KP | 结构化剧本和生成质量报告。 |
| Engine | 开局时初始化权威状态。 |

## 用户故事

| 编号 | 用户故事 | 优先级 |
|---|---|---:|
| MOD-1 | 作为房主，我能上传 PDF 并得到结构化剧本。 | P0 |
| MOD-2 | 作为创作者，我能锁定模组真相。 | P0 |
| MOD-3 | 作为房主，我能看到质量报告再开局。 | P0 |
| MOD-4 | 作为房主，我能从模组一键创建房间。 | P0 |

## 数据边界

模组数据包括 metadata、truth、scenes、npcs、clues、items、events、endings、assets、promptConfig、qualityReport。房间运行态从模组初始化后独立演化，不反写原始模组。

## 接口 / 事件方向

- REST：导入 PDF、查询结构化结果、编辑模组、质量报告、一键开房。
- Event：`module_imported`、`scenario_structured`、`quality_report_generated`、`room_created_from_module`。
- AI：结构化输出必须校验 schema。

## 验收标准

- PDF 文本可抽取并结构化。
- 质量报告能指出完整性、防剧透、角色适配和素材缺口。
- 一键开局能生成房间和初始状态。
- 模组真相不进入玩家投影。

