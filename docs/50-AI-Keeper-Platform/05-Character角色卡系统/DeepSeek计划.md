# Character 角色卡系统 DeepSeek 计划初版

## 执行定位

Character 模块先围绕 COC 角色导入、绑定、查看和技能检定稳定；角色创建器和成长进入后续批。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Character-1 | 稳定 xlsx 导入和字段适配 | `src/server/scenario/xlsx_parser.py`、`tests/server/test_xlsx_parser.py` | `python -m pytest tests/server/test_xlsx_parser.py -q` | 不把解析失败静默吞掉。 |
| Character-2 | 角色绑定和私密字段过滤 | `src/server/player/router_player.py`、`tests/server/test_character_join_import.py` | `python -m pytest tests/server/test_character_join_import.py -q` | 不让玩家查看他人私密信息。 |
| Character-3 | 角色状态与技能检定联动 | `src/server/engine/skill_check.py`、`tests/server/test_player_features.py` | `python -m pytest tests/server/test_player_features.py -q` | 不让前端本地角色卡覆盖后端状态。 |

## DeepSeek 执行规则

- 所有角色状态以服务端为准。
- 导入报告要说明缺失字段和默认值。
- 私密字段进入 AI 上下文前必须经过裁剪。

