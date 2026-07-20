from src.server.scenario.quality import QualityReportGenerator, QualityLevel


def test_ready_scenario():
    gen = QualityReportGenerator()
    graph = {
        "scenes": [{"name": "intro"}, {"name": "climax"}],
        "npcs": [{"name": "Bob", "npc_id": "npc-bob", "personality": "可疑"}],
        "clues": [{"name": "letter"}],
        "truth": {"summary": "Bob did it"},
        "spoiler_boundaries": {"public": ["intro"]},
        "endings": [{"name": "good"}],
    }
    report = gen.evaluate(graph)
    assert report.level == QualityLevel.READY
    assert report.completeness == 1.0


def test_warning_missing_ending():
    gen = QualityReportGenerator()
    graph = {
        "scenes": [{"name": "intro"}],
        "npcs": [{"name": "Bob", "npc_id": "npc-bob", "personality": "可疑"}],
        "clues": [{"name": "letter"}],
        "truth": {"summary": "Bob did it"},
        "spoiler_boundaries": {"public": ["intro"]},
        "endings": [],
    }
    report = gen.evaluate(graph)
    assert report.level == QualityLevel.WARNING
    assert any(i.severity == "warning" for i in report.issues)


def test_high_risk_multiple_warnings():
    gen = QualityReportGenerator()
    graph = {
        "scenes": [{"name": "intro"}],
        "npcs": [],
        "clues": [],
        "truth": None,
        "endings": [],
    }
    report = gen.evaluate(graph)
    assert report.level == QualityLevel.HIGH_RISK


def test_blocked_empty_graph():
    gen = QualityReportGenerator()
    report = gen.evaluate({})
    assert report.level == QualityLevel.BLOCKED


def test_blocked_no_scenes():
    gen = QualityReportGenerator()
    graph = {"scenes": [], "npcs": [{"name": "Bob", "npc_id": "npc-bob", "personality": "可疑"}], "clues": [], "truth": {}, "endings": []}
    report = gen.evaluate(graph)
    assert report.level == QualityLevel.BLOCKED


def test_scene_asset_binding_satisfies_image_quality_check():
    report = QualityReportGenerator().evaluate({
        "scenes": [{"scene_id": "study", "name": "书房", "image_asset_id": "asset-study"}],
        "npcs": [{"name": "Bob", "npc_id": "npc-bob", "personality": "可疑"}],
        "clues": [{"name": "letter"}],
        "truth": {"summary": "失踪案与地下祭坛有关"},
        "endings": [{"ending_id": "escape", "name": "逃离"}],
    })

    assert all(issue.code != "scene_images_missing" for issue in report.issues)


def test_quality_report_surfaces_missing_npc_item_and_clue_images_as_optional_work():
    report = QualityReportGenerator().evaluate({
        "scenes": [{"scene_id": "study", "name": "书房", "image_asset_id": "asset-study"}],
        "npcs": [{"npc_id": "keeper", "name": "馆长", "image_asset_id": "asset-keeper"}],
        "items": [{"item_id": "brass-key", "name": "黄铜钥匙"}],
        "clues": [{"clue_id": "blood-letter", "name": "血信"}],
        "truth": {"summary": "失踪案与地下祭坛有关"},
        "endings": [{"ending_id": "escape", "name": "逃离"}],
    })

    issue = next(item for item in report.issues if item.code == "supporting_images_missing")

    assert issue.blocking is False
    assert issue.severity == "info"
    assert issue.target_type == "asset"
