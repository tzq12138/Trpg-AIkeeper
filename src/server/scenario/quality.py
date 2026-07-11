from enum import Enum
from pydantic import BaseModel


class QualityLevel(str, Enum):
    READY = "ready"
    WARNING = "warning"
    HIGH_RISK = "highRisk"
    BLOCKED = "blocked"


class QualityIssue(BaseModel):
    category: str
    severity: str
    message: str


class QualityReport(BaseModel):
    level: QualityLevel
    issues: list[QualityIssue] = []
    completeness: float = 0.0


class QualityReportGenerator:
    def evaluate(self, knowledge_graph: dict) -> QualityReport:
        issues: list[QualityIssue] = []

        if not knowledge_graph:
            return QualityReport(
                level=QualityLevel.BLOCKED,
                issues=[
                    QualityIssue(
                        category="structure",
                        severity="critical",
                        message="无法抽取任何结构化内容",
                    )
                ],
            )

        scenes = knowledge_graph.get("scenes", [])
        npcs = knowledge_graph.get("npcs", [])
        clues = knowledge_graph.get("clues", [])
        truth = knowledge_graph.get("truth")
        endings = knowledge_graph.get("endings", [])

        if not scenes:
            issues.append(
                QualityIssue(category="completeness", severity="critical", message="未识别到场景")
            )
        if not npcs:
            issues.append(
                QualityIssue(category="completeness", severity="warning", message="未识别到NPC")
            )
        else:
            # Check NPC field quality
            npcs_missing_id = [n.get("name", f"NPC#{i}") for i, n in enumerate(npcs) if not n.get("npc_id")]
            if npcs_missing_id:
                issues.append(
                    QualityIssue(category="schema", severity="warning",
                                 message=f"{len(npcs_missing_id)}个NPC缺少npc_id: {', '.join(npcs_missing_id[:3])}")
                )
            hidden_npcs = [n for n in npcs if n.get("is_hidden")]
            hidden_without_public = [n.get("name", "?") for n in hidden_npcs if not n.get("public_description")]
            if hidden_without_public:
                issues.append(
                    QualityIssue(category="spoiler", severity="warning",
                                 message=f"隐藏NPC缺少public_description: {', '.join(hidden_without_public[:3])}")
                )
            npcs_without_personality = [n.get("name", "?") for n in npcs if not n.get("personality")]
            if len(npcs_without_personality) >= len(npcs) // 2:
                issues.append(
                    QualityIssue(category="completeness", severity="info",
                                 message=f"多数NPC缺少personality字段（影响AI扮演质量）")
                )
        if not clues:
            issues.append(
                QualityIssue(category="completeness", severity="warning", message="未识别到线索")
            )
        if not truth:
            issues.append(
                QualityIssue(category="spoiler", severity="warning", message="未识别到真相")
            )
        if not endings:
            issues.append(
                QualityIssue(category="completeness", severity="warning", message="未识别到结局")
            )

        if truth and not knowledge_graph.get("spoiler_boundaries"):
            issues.append(
                QualityIssue(category="spoiler", severity="warning", message="未定义防剧透边界")
            )

        solo_adventure = knowledge_graph.get("solo_adventure")
        if isinstance(solo_adventure, dict):
            integrity = solo_adventure.get("integrity")
            if isinstance(integrity, dict) and not integrity.get("is_valid", True):
                duplicates = integrity.get("duplicate_node_ids") or []
                missing = integrity.get("missing_target_node_ids") or []
                details = []
                if duplicates:
                    details.append(f"重复条目: {', '.join(map(str, duplicates[:5]))}")
                if missing:
                    details.append(f"无效跳转目标: {', '.join(map(str, missing[:5]))}")
                issues.append(
                    QualityIssue(
                        category="solo_adventure",
                        severity="critical",
                        message="编号单人冒险分支图无效" + (f"（{'；'.join(details)}）" if details else ""),
                    )
                )
            elif isinstance(integrity, dict) and integrity.get("unreachable_node_ids"):
                issues.append(
                    QualityIssue(
                        category="solo_adventure",
                        severity="info",
                        message=f"存在 {len(integrity['unreachable_node_ids'])} 个当前不可达条目，保留供条件分支使用",
                    )
                )

        recommended = knowledge_graph.get("recommended_tags", [])
        if recommended and not knowledge_graph.get("key_skills"):
            issues.append(
                QualityIssue(category="adaptation", severity="warning", message="缺少关键技能推荐")
            )

        scenes_with_images = [s for s in scenes if s.get("image_url")]
        if scenes and not scenes_with_images:
            issues.append(
                QualityIssue(category="assets", severity="info", message="场景缺少配图")
            )

        has_critical = any(i.severity == "critical" for i in issues)
        significant = [i for i in issues if i.severity != "info"]
        if has_critical:
            level = QualityLevel.BLOCKED
        elif len(significant) >= 3:
            level = QualityLevel.HIGH_RISK
        elif significant:
            level = QualityLevel.WARNING
        else:
            level = QualityLevel.READY

        total = 5
        present = sum(1 for x in [scenes, npcs, clues, truth, endings] if x)
        completeness = present / total

        return QualityReport(level=level, issues=issues, completeness=completeness)
