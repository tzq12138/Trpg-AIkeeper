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
    code: str = ""
    blocking: bool = False
    target_type: str = ""
    target_key: str = ""
    resolution_hint: str = ""


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
                    _issue(
                        "structure", "critical", "无法抽取任何结构化内容",
                        code="empty_structure", blocking=True,
                        target_type="scenario", resolution_hint="重新研读原件或补充基础场景、人物和线索",
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
                _issue(
                    "completeness", "critical", "未识别到场景",
                    code="missing_scenes", blocking=True,
                    target_type="scene", resolution_hint="补充至少一个可进入的场景",
                )
            )
        if not npcs:
            issues.append(
                _issue(
                    "completeness", "warning", "未识别到NPC",
                    code="missing_npcs", blocking=True,
                    target_type="npc", resolution_hint="补充至少一个可互动 NPC",
                )
            )
        else:
            # Check NPC field quality
            npcs_missing_id = [n.get("name", f"NPC#{i}") for i, n in enumerate(npcs) if not n.get("npc_id")]
            if npcs_missing_id:
                issues.append(
                    _issue(
                        "schema", "warning",
                        f"{len(npcs_missing_id)}个NPC缺少npc_id: {', '.join(npcs_missing_id[:3])}",
                        code="npc_missing_id", blocking=True, target_type="npc",
                        resolution_hint="为每个 NPC 生成稳定且唯一的 npc_id",
                    )
                )
            hidden_npcs = [n for n in npcs if n.get("is_hidden")]
            hidden_without_public = [n.get("name", "?") for n in hidden_npcs if not n.get("public_description")]
            if hidden_without_public:
                issues.append(
                    _issue(
                        "spoiler", "warning",
                        f"隐藏NPC缺少public_description: {', '.join(hidden_without_public[:3])}",
                        code="hidden_npc_missing_public_description", blocking=True,
                        target_type="npc", resolution_hint="补充不剧透的公开描述",
                    )
                )
            npcs_without_personality = [n.get("name", "?") for n in npcs if not n.get("personality")]
            if len(npcs_without_personality) >= len(npcs) // 2:
                issues.append(
                    _issue(
                        "completeness", "info", "多数NPC缺少personality字段（影响AI扮演质量）",
                        code="npc_personality_incomplete", target_type="npc",
                        resolution_hint="补充 NPC 性格、目标或说话风格",
                    )
                )
        if not clues:
            issues.append(
                _issue(
                    "completeness", "warning", "未识别到线索",
                    code="missing_clues", blocking=True, target_type="clue",
                    resolution_hint="补充至少一条可发现的线索",
                )
            )
        if not truth:
            issues.append(
                _issue(
                    "spoiler", "warning", "未识别到真相",
                    code="missing_truth", blocking=True, target_type="truth",
                    resolution_hint="补充幕后真相及其可揭示范围",
                )
            )
        if not endings:
            issues.append(
                _issue(
                    "completeness", "warning", "未识别到结局",
                    code="missing_endings", blocking=True, target_type="ending",
                    resolution_hint="补充至少一个可达结局和完成条件",
                )
            )

        if truth and not knowledge_graph.get("spoiler_boundaries"):
            issues.append(_issue(
                "spoiler", "warning", "未定义防剧透边界",
                code="missing_spoiler_boundaries", blocking=True,
                target_type="spoiler_boundary", resolution_hint="定义玩家、房主和管理员可见边界",
            ))

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
                    _issue(
                        "solo_adventure", "critical",
                        "编号单人冒险分支图无效" + (f"（{'；'.join(details)}）" if details else ""),
                        code="solo_branch_graph_invalid", blocking=True,
                        target_type="branch", resolution_hint="修复重复条目和无效跳转目标",
                    )
                )
            elif isinstance(integrity, dict) and integrity.get("unreachable_node_ids"):
                issues.append(
                    _issue(
                        "solo_adventure", "info",
                        f"存在 {len(integrity['unreachable_node_ids'])} 个当前不可达条目，保留供条件分支使用",
                        code="solo_unreachable_nodes", target_type="branch",
                        resolution_hint="确认这些条目由条件分支抵达，或修复连接",
                    )
                )

        recommended = knowledge_graph.get("recommended_tags", [])
        if recommended and not knowledge_graph.get("key_skills"):
            issues.append(
                _issue(
                    "adaptation", "warning", "缺少关键技能推荐",
                    code="missing_key_skills", target_type="rule",
                    resolution_hint="补充推荐技能和对应剧本依据",
                )
            )

        scenes_with_images = [s for s in scenes if s.get("image_url")]
        if scenes and not scenes_with_images:
            issues.append(
                _issue(
                    "assets", "info", "场景缺少配图",
                    code="scene_images_missing", target_type="asset",
                    resolution_hint="绑定场景配图，或在审核台声明文字场景模式",
                )
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


def _issue(
    category: str,
    severity: str,
    message: str,
    *,
    code: str,
    blocking: bool = False,
    target_type: str = "",
    target_key: str = "",
    resolution_hint: str = "",
) -> QualityIssue:
    return QualityIssue(
        category=category,
        severity=severity,
        message=message,
        code=code,
        blocking=blocking,
        target_type=target_type,
        target_key=target_key,
        resolution_hint=resolution_hint,
    )
