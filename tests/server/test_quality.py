from src.server.quality import QualityReportGenerator, QualityLevel


def test_ready_scenario():
    gen = QualityReportGenerator()
    graph = {
        "scenes": [{"name": "intro"}, {"name": "climax"}],
        "npcs": [{"name": "Bob"}],
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
        "npcs": [{"name": "Bob"}],
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
    graph = {"scenes": [], "npcs": [{"name": "Bob"}], "clues": [], "truth": {}, "endings": []}
    report = gen.evaluate(graph)
    assert report.level == QualityLevel.BLOCKED
