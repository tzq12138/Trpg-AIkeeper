# AI-Keeper 原创黄金模组

本目录提供三套**完全原创、仅授权私用**的结构化剧本黄金样本，用于验证剧本导入、世界书/RAG、文字地图、预设角色、CoC7 规则绑定和开房前质量检查。

| 目录 | 人数 | 类型 | 文字地图 |
| --- | --- | --- | --- |
| `01-solo-tutorial-tide-letter` | 1 | 单人教学 | 3 个节点 |
| `02-short-team-glass-rain` | 2–4 | 短团 | 4 个节点 |
| `03-investigation-sandbox-lost-property` | 3–5 | 调查沙盒 | 6 个节点 |

## 文件契约

每个目录包含：

- `module.json`：唯一机器可读来源。`knowledge_graph` 对应运行时 `ScenarioKnowledgeGraph`，`character_templates` 对应 `character_templates` 表字段，`quality_report` 对应 `QualityReport`。
- `README.md`：主持人可读的验收路径与信息边界。

当前仓库没有可直接导入这一 JSON 格式的公开 API；它是供导入/迁移实现、数据库 fixture 和人工验收使用的**规范化黄金输入**，而不是声称可直接上传的运行包。接入时应保留 `manifest`、`citations` 和 `license`，并将 `knowledge_graph`、预设角色和文字地图分别写入现有的剧本、角色模板和地图存储层。

## 字段映射

| `module.json` 字段 | 当前契约 | 说明 |
| --- | --- | --- |
| `knowledge_graph.scenes/npcs/clues/truth/endings` | `ScenarioKnowledgeGraph` | NPC 均有稳定 `npc_id`；隐藏 NPC 均有 `public_description`。 |
| `knowledge_graph.key_skills`、`recommended_tags`、`rule_citations` | 备团包/RAG 扩展字段 | 不复制规则书原文，只声明应绑定的已授权 CoC7 规则版本。 |
| `character_templates` | `character_templates` | 使用 `name/occupation/background/age/gender/attributes/skills/backstory`。 |
| `scenario_assets.text_map` | 文字场景回退 | 使用 `nodes/edges` 描述可移动节点；不包含图片或外部素材。 |
| `citations` | 来源锚点 | 都锚定在同一原创 JSON 内，用于导入后的 citation 定位回归。 |
| `quality_report` | `QualityReport` | 预期为 `ready`、完整度 `1.0`；文字地图会保留“场景缺少配图”的 info 项。 |

## 授权与安全边界

- 三套故事、人物、地点、线索和文字地图均为本项目新创作，不改编或复用任何受版权保护的模组、小说、插画、地图或规则原文。
- `AI-Keeper-Original-Private-Use-1.0` 允许本地或私有房间使用、测试和修改；不授权商业发行、公开再分发或把内容伪称为官方规则资料。
- `rules_binding` 仅引用部署中已获授权的 `coc7` RuleSet 版本。它不携带 CoC7 规则正文，部署方仍须自行保证规则资料授权。
- `truth`、隐藏 NPC 和隐藏线索是 Host/AI 专用输入；玩家投影只能在剧情公开后显示相应的公开描述或线索摘要。

## 最小验证

在仓库根目录运行以下命令：

```powershell
Get-ChildItem data/golden_modules -Recurse -Filter module.json |
  ForEach-Object { python -m json.tool $_.FullName | Out-Null }

@'
import json
from pathlib import Path
from src.server.models import ScenarioKnowledgeGraph
from src.server.scenario.quality import QualityReportGenerator

for path in sorted(Path("data/golden_modules").glob("*/module.json")):
    module = json.loads(path.read_text(encoding="utf-8"))
    graph = ScenarioKnowledgeGraph.model_validate(module["knowledge_graph"])
    report = QualityReportGenerator().evaluate(module["knowledge_graph"])
    assert report.level.value == "ready", (path, report)
    assert report.completeness == 1.0, (path, report)
    assert module["quality_report"]["level"] == report.level.value, path
    assert len(module["character_templates"]) >= module["manifest"]["player_count"]["min"], path
print("golden modules valid")
'@ | python -
```
