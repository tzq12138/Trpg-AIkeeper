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
