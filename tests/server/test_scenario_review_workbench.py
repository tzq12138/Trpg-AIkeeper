import json
import base64

import pytest
from fastapi.testclient import TestClient

from src.server.engine.engine import Engine
from src.server.main import app
from src.server.router_auth import _hash_password
from src.server.scenario.quality import QualityReportGenerator


def test_quality_report_emits_blocking_actionable_issue_for_missing_clues():
    report = QualityReportGenerator().evaluate({
        "scenes": [{"scene_id": "study", "name": "书房"}],
        "npcs": [{"npc_id": "keeper", "name": "馆长"}],
        "truth": {"summary": "失踪案与地下祭坛有关"},
        "endings": [{"ending_id": "escape", "name": "逃离"}],
        "spoiler_boundaries": [{
            "id": "truth",
            "target_type": "truth",
            "target_id": "truth",
            "player_visibility": "hidden",
            "host_visibility": "complete",
            "player_description": "调查背后另有隐情。",
            "unlock_clues": [],
            "citation": {"source_part_id": "review-part-1", "page_number": 1},
        }, {
            "id": "ending:escape",
            "target_type": "ending",
            "target_id": "escape",
            "player_visibility": "hidden",
            "host_visibility": "complete",
            "player_description": "调查的结果仍有多种可能。",
            "unlock_clues": [],
            "citation": {"source_part_id": "review-part-1", "page_number": 1},
        }],
    })

    issue = next(item for item in report.issues if item.code == "missing_clues")

    assert issue.blocking is True
    assert issue.target_type == "clue"
    assert issue.resolution_hint == "补充至少一条可发现的线索"


def test_review_quality_requires_explicit_cited_spoiler_boundaries():
    graph = {
        "scenes": [{"scene_id": "study", "name": "书房"}],
        "npcs": [{"npc_id": "keeper", "name": "馆长", "is_hidden": True}],
        "clues": [{"clue_id": "letter", "name": "密信", "is_hidden": True}],
        "truth": {"summary": "馆长在地下室举行仪式"},
        "endings": [{"ending_id": "escape", "name": "逃离", "description": "阻止仪式后离开"}],
        "spoiler_boundaries": [{
            "id": "truth",
            "target_type": "truth",
            "target_id": "truth",
            "player_visibility": "hidden",
            "host_visibility": "complete",
            "player_description": "调查背后另有隐情。",
            "unlock_clues": [],
            "citation": {"source_part_id": "review-part-1", "page_number": 1},
        }],
    }

    report = QualityReportGenerator().evaluate(
        graph,
        require_complete_spoiler_boundaries=True,
    )

    issue = next(item for item in report.issues if item.code == "spoiler_boundary_coverage_incomplete")
    assert issue.blocking is True
    assert issue.target_type == "spoiler_boundary"


def test_review_quality_requires_boundary_for_hidden_module_asset():
    graph = {
        "scenes": [{"scene_id": "study", "name": "书房"}],
        "npcs": [{"npc_id": "keeper", "name": "馆长"}],
        "clues": [{"clue_id": "letter", "name": "密信"}],
        "truth": {},
        "endings": [],
        "assets": {"items": {
            "sealed-letter": {"name": "封存信件", "is_secret": True},
        }},
        "spoiler_boundaries": [],
    }

    report = QualityReportGenerator().evaluate(
        graph,
        require_complete_spoiler_boundaries=True,
    )

    issue = next(item for item in report.issues if item.code == "spoiler_boundary_coverage_incomplete")
    assert "私密素材 封存信件" in issue.message


def _seed_review_version(test_db):
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title) VALUES ('review-scenario', '审核台测试')"
    )
    test_db.execute(
        """
        INSERT INTO source_documents (
            source_document_id, scenario_id, source_kind, title, source_filename,
            mime_type, source_sha256, storage_path, license_type, created_by
        ) VALUES ('review-source', 'review-scenario', 'scenario', '审核原件',
                  'review.pdf', 'application/pdf', 'review-sha', 'review.pdf',
                  'authorized', 'admin')
        """
    )
    test_db.execute(
        """
        INSERT INTO source_parts (
            source_part_id, source_document_id, ordinal, part_kind, page_number,
            text_content, anchor, checksum
        ) VALUES ('review-part-1', 'review-source', 1, 'page', 1,
                  '书房内发现了沾血的信封。', %s, 'part-sha')
        """,
        (json.dumps({"page_number": 1, "anchor": "opening"}),),
    )
    graph = {
        "scenes": [{"scene_id": "study", "name": "书房"}],
        "npcs": [{"npc_id": "keeper", "name": "馆长"}],
        "truth": {"summary": "祭坛与失踪案有关"},
        "endings": [{"ending_id": "escape", "name": "逃离"}],
        "spoiler_boundaries": [{
            "id": "truth",
            "target_type": "truth",
            "target_id": "truth",
            "player_visibility": "hidden",
            "host_visibility": "complete",
            "player_description": "调查背后另有隐情。",
            "unlock_clues": [],
            "citation": {"source_part_id": "review-part-1", "page_number": 1},
        }, {
            "id": "ending:escape",
            "target_type": "ending",
            "target_id": "escape",
            "player_visibility": "hidden",
            "host_visibility": "complete",
            "player_description": "调查的结果仍有多种可能。",
            "unlock_clues": [],
            "citation": {"source_part_id": "review-part-1", "page_number": 1},
        }],
    }
    quality = QualityReportGenerator().evaluate(graph).model_dump(mode="json")
    test_db.execute(
        """
        INSERT INTO scenario_versions (
            scenario_version_id, scenario_id, version_number, status,
            knowledge_graph, quality_report, prep_package, created_by
        ) VALUES ('review-v1', 'review-scenario', 1, 'draft_review', %s, %s, %s, 'admin')
        """,
        (json.dumps(graph, ensure_ascii=False), json.dumps(quality, ensure_ascii=False), json.dumps({"summary": "测试备团包"})),
    )
    test_db.execute(
        "INSERT INTO scenario_version_sources (scenario_version_id, source_document_id, ordinal) "
        "VALUES ('review-v1', 'review-source', 1)"
    )
    test_db.commit()


@pytest.fixture
def review_client(test_db):
    client = TestClient(app)
    app.state.db = test_db
    app.state.engine = Engine(test_db)
    for account_id, username, role in (
        ("review-admin", "reviewadmin", "admin"),
        ("review-host", "reviewhost", "host"),
    ):
        test_db.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES (%s, %s, %s, %s, %s)",
            (account_id, username, _hash_password("test123"), username, role),
        )
    test_db.commit()
    return client


def _token(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def test_review_workbench_exposes_original_parts_and_actionable_issues(test_db):
    from src.server.scenario.review_service import ScenarioReviewService

    _seed_review_version(test_db)

    workspace = ScenarioReviewService(test_db).get_workbench("review-scenario", "review-v1")

    assert workspace["source_parts"][0]["source_part_id"] == "review-part-1"
    issue = next(item for item in workspace["issues"] if item["code"] == "missing_clues")
    assert issue["blocking"] is True
    assert issue["status"] == "open"


def test_create_review_draft_copies_sources_without_mutating_parent(test_db):
    from src.server.scenario.review_service import ScenarioReviewService

    _seed_review_version(test_db)
    draft = ScenarioReviewService(test_db).create_review_draft(
        "review-scenario", "review-v1", created_by="admin"
    )

    assert draft["parent_version_id"] == "review-v1"
    assert draft["version_number"] == 2
    copied_source = test_db.execute(
        "SELECT source_document_id FROM scenario_version_sources WHERE scenario_version_id = %s",
        (draft["scenario_version_id"],),
    ).fetchone()
    assert copied_source["source_document_id"] == "review-source"
    parent = test_db.execute(
        "SELECT status FROM scenario_versions WHERE scenario_version_id = 'review-v1'"
    ).fetchone()
    assert parent["status"] == "draft_review"


def test_review_patch_requires_source_citation_or_curator_rationale(test_db):
    from src.server.scenario.review_service import ScenarioReviewError, ScenarioReviewService

    _seed_review_version(test_db)
    service = ScenarioReviewService(test_db)
    draft = service.create_review_draft("review-scenario", "review-v1", created_by="admin")

    with pytest.raises(ScenarioReviewError, match="review_patch_evidence_required"):
        service.add_patch(
            draft["scenario_version_id"],
            target_type="clue",
            target_key="blood-envelope",
            payload={"clue_id": "blood-envelope", "name": "沾血的信封"},
            provenance="source",
            citation={},
            rationale="",
            created_by="admin",
        )


def test_rebuild_review_draft_merges_cited_patch_and_resolves_quality_issue(test_db):
    from src.server.scenario.review_service import ScenarioReviewService

    _seed_review_version(test_db)
    service = ScenarioReviewService(test_db)
    draft = service.create_review_draft("review-scenario", "review-v1", created_by="admin")
    service.add_patch(
        draft["scenario_version_id"],
        target_type="clue",
        target_key="blood-envelope",
        payload={"clue_id": "blood-envelope", "name": "沾血的信封", "location": "书房"},
        provenance="source",
        citation={"source_part_id": "review-part-1", "source_ref": "review.pdf#page=1"},
        rationale="",
        created_by="admin",
    )

    rebuilt = service.rebuild_review_draft(draft["scenario_version_id"], requested_by="admin")

    assert rebuilt["quality_report"]["level"] == "ready"
    assert rebuilt["knowledge_graph"]["clues"][0]["citation"]["source_part_id"] == "review-part-1"
    workspace = service.get_workbench("review-scenario", draft["scenario_version_id"])
    assert all(issue["code"] != "missing_clues" for issue in workspace["issues"])


def test_review_waiver_rejects_blocking_issue_and_tracks_nonblocking_rationale(test_db):
    from src.server.scenario.review_service import ScenarioReviewError, ScenarioReviewService

    _seed_review_version(test_db)
    service = ScenarioReviewService(test_db)
    draft = service.create_review_draft("review-scenario", "review-v1", created_by="admin")
    draft_id = draft["scenario_version_id"]

    with pytest.raises(ScenarioReviewError, match="review_issue_cannot_be_waived"):
        service.resolve_issue(
            draft_id,
            issue_id="quality:missing_clues",
            resolution="not_applicable",
            rationale="不想补线索",
            created_by="admin",
        )

    service.add_patch(
        draft_id,
        target_type="clue",
        target_key="clue-archive-key",
        payload={"clue_id": "clue-archive-key", "name": "档案室钥匙", "text": "钥匙藏在书架后。"},
        provenance="source",
        citation={"source_part_id": "review-part-1", "page_number": 1},
        rationale="",
        created_by="admin",
    )
    service.rebuild_review_draft(draft_id, requested_by="admin")
    result = service.resolve_issue(
        draft_id,
        issue_id="quality:scene_images_missing",
        resolution="not_applicable",
        rationale="本模组采用纯文字场景模式。",
        created_by="admin",
    )

    assert result["status"] == "not_applicable"
    issue = next(
        item
        for item in service.get_workbench("review-scenario", draft_id)["issues"]
        if item["issue_id"] == "quality:scene_images_missing"
    )
    assert issue["status"] == "not_applicable"
    assert issue["resolution_rationale"] == "本模组采用纯文字场景模式。"


def test_review_draft_with_blocking_issue_cannot_be_published(review_client, test_db):
    _seed_review_version(test_db)
    token = _token(review_client, "reviewadmin")
    headers = {"Authorization": f"Bearer {token}"}
    created = review_client.post(
        "/api/scenarios/review-scenario/versions/review-v1/review-drafts",
        headers=headers,
    )
    assert created.status_code == 200, created.text

    response = review_client.post(
        "/api/scenarios/review-scenario/versions/"
        f"{created.json()['scenario_version_id']}/publish",
        headers=headers,
        json={"confirm": True, "review_notes": "尝试跳过核心线索"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "review_incomplete"
    assert response.json()["detail"]["issues"][0]["code"] == "missing_clues"


def test_review_issue_resolution_api_requires_reason_and_returns_resolution(review_client, test_db):
    from src.server.scenario.review_service import ScenarioReviewService

    _seed_review_version(test_db)
    token = _token(review_client, "reviewadmin")
    headers = {"Authorization": f"Bearer {token}"}
    created = review_client.post(
        "/api/scenarios/review-scenario/versions/review-v1/review-drafts",
        headers=headers,
    )
    draft_id = created.json()["scenario_version_id"]
    service = ScenarioReviewService(test_db)
    service.add_patch(
        draft_id,
        target_type="clue",
        target_key="blood-envelope",
        payload={"clue_id": "blood-envelope", "name": "沾血的信封"},
        provenance="source",
        citation={"source_part_id": "review-part-1"},
        rationale="",
        created_by="admin",
    )
    service.rebuild_review_draft(draft_id, requested_by="admin")

    response = review_client.post(
        f"/api/scenarios/review-scenario/versions/{draft_id}/review-issues/resolve",
        headers=headers,
        json={
            "issue_id": "quality:scene_images_missing",
            "resolution": "not_applicable",
            "rationale": "纯文字场景模式。",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "not_applicable"


@pytest.mark.asyncio
async def test_review_ai_suggests_uncommitted_cited_patch_for_selected_issue(test_db):
    from src.server.scenario.review_service import ScenarioReviewService

    class ReviewGateway:
        async def review_scenario(self, context):
            assert context["mode"] == "issue"
            assert context["issue"]["code"] == "missing_clues"
            return {
                "summary": "原文的血信封可整理为开场线索。",
                "suggestions": [{
                    "target_type": "clue",
                    "target_key": "blood-envelope",
                    "payload": {"clue_id": "blood-envelope", "name": "沾血的信封"},
                    "provenance": "source",
                    "citation": {"source_part_id": "review-part-1", "page_number": 1},
                    "confidence": 0.91,
                }],
            }

    _seed_review_version(test_db)
    service = ScenarioReviewService(test_db, gateway=ReviewGateway())
    draft = service.create_review_draft("review-scenario", "review-v1", created_by="admin")

    result = await service.suggest_issue_drafts(
        "review-scenario",
        draft["scenario_version_id"],
        issue_id="quality:missing_clues",
    )

    assert result["summary"] == "原文的血信封可整理为开场线索。"
    assert result["suggestions"][0]["citation"]["source_part_id"] == "review-part-1"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM scenario_review_patches WHERE scenario_version_id = %s",
        (draft["scenario_version_id"],),
    ).fetchone()["count"] == 0


@pytest.mark.asyncio
async def test_review_ai_filters_uncited_or_incomplete_spoiler_boundary_candidates(test_db):
    from src.server.scenario.review_service import ScenarioReviewService

    class ReviewGateway:
        async def review_scenario(self, context):
            assert context["issue"]["code"] == "missing_spoiler_boundaries"
            return {
                "summary": "原文明确了仪式真相与可发现信件。",
                "suggestions": [
                    {
                        "target_type": "spoiler_boundary",
                        "target_key": "truth",
                        "payload": {
                            "id": "truth",
                            "target_type": "truth",
                            "target_id": "truth",
                            "player_visibility": "hidden",
                            "host_visibility": "complete",
                            "player_description": "调查背后另有隐情。",
                            "unlock_clues": ["blood-envelope"],
                        },
                        "provenance": "source",
                        "citation": {"source_part_id": "review-part-1", "page_number": 1},
                        "confidence": 0.93,
                    },
                    {
                        "target_type": "spoiler_boundary",
                        "target_key": "ending:escape",
                        "payload": {"id": "ending:escape", "target_type": "ending"},
                        "provenance": "source",
                        "citation": {"source_part_id": "review-part-1", "page_number": 1},
                        "confidence": 0.71,
                    },
                ],
            }

    _seed_review_version(test_db)
    service = ScenarioReviewService(test_db, gateway=ReviewGateway())
    draft = service.create_review_draft(
        "review-scenario",
        "review-v1",
        created_by="admin",
    )
    draft_id = draft["scenario_version_id"]
    test_db.execute(
        "UPDATE scenario_versions SET quality_report = %s WHERE scenario_version_id = %s",
        (json.dumps({
            "level": "warning",
            "issues": [{
                "code": "missing_spoiler_boundaries",
                "category": "spoiler",
                "severity": "warning",
                "message": "未定义防剧透边界",
                "blocking": True,
                "target_type": "spoiler_boundary",
            }],
        }, ensure_ascii=False), draft_id),
    )
    test_db.commit()

    result = await service.suggest_issue_drafts(
        "review-scenario",
        draft_id,
        issue_id="quality:missing_spoiler_boundaries",
    )

    assert [item["target_key"] for item in result["suggestions"]] == ["truth"]
    assert result["suggestions"][0]["payload"]["player_visibility"] == "hidden"


@pytest.mark.asyncio
async def test_scene_image_suggestion_preview_and_adoption_are_separate_steps(test_db, tmp_path):
    from src.server.scenario.scene_image_service import SceneImageService

    tiny_png = (
        "data:image/png;base64,"
        + base64.b64encode(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\x0dIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        ).decode("ascii")
    )

    class ImageGateway:
        def __init__(self):
            self.generated_prompt = ""

        async def suggest_scene_images(self, context):
            assert [scene["scene_id"] for scene in context["scenes"]] == ["cellar"]
            return {
                "summary": "地下室适合补一张氛围图。",
                "suggestions": [{
                    "scene_id": "cellar",
                    "image_summary": "潮湿石阶通向昏暗地下室。",
                    "prompt": "潮湿石阶旁露出邪教祭坛和失踪者名字。",
                    "style": "1920s investigation, painterly",
                    "citation": {"source_part_id": "review-part-1", "page_number": 1},
                    "confidence": 0.89,
                }],
            }

        async def generate_scene_image(self, context):
            self.generated_prompt = context["prompt"]
            return {"data_url": tiny_png, "mime_type": "image/png"}

    _seed_review_version(test_db)
    from src.server.scenario.review_service import ScenarioReviewService

    draft = ScenarioReviewService(test_db).create_review_draft(
        "review-scenario",
        "review-v1",
        created_by="admin",
    )
    draft_id = draft["scenario_version_id"]
    graph = {
        "scenes": [
            {"scene_id": "study", "name": "书房", "image_asset_id": "existing-image"},
            {
                "scene_id": "cellar",
                "name": "地下室",
                "description": "邪教祭坛上刻着失踪者姓名。",
                "public_description": "潮湿石阶通向昏暗地下室。",
            },
        ],
        "npcs": [{"npc_id": "keeper", "name": "馆长"}],
        "clues": [{"clue_id": "blood-envelope", "name": "沾血的信封"}],
        "truth": {"summary": "祭坛与失踪案有关"},
        "endings": [{"ending_id": "escape", "name": "逃离"}],
        "spoiler_boundaries": [{"id": "truth", "level": "keeper"}],
    }
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), draft_id),
    )
    test_db.commit()
    gateway = ImageGateway()
    service = SceneImageService(test_db, gateway=gateway, asset_root=tmp_path)

    suggested = await service.suggest("review-scenario", draft_id)

    assert suggested["suggestions"][0]["visibility"] == "host_only"
    assert test_db.execute("SELECT COUNT(*) AS count FROM scenario_assets").fetchone()["count"] == 0
    assert test_db.execute("SELECT COUNT(*) AS count FROM scenario_asset_bindings").fetchone()["count"] == 0

    preview = await service.preview(
        "review-scenario",
        draft_id,
        suggestion=suggested["suggestions"][0],
        prompt="请把秘密祭坛画得更清楚。",
        visibility="party",
        size="1024x1024",
    )

    assert preview["visibility"] == "party"
    assert "邪教" not in gateway.generated_prompt
    assert "失踪者" not in gateway.generated_prompt
    assert "潮湿石阶" in gateway.generated_prompt
    assert test_db.execute("SELECT COUNT(*) AS count FROM scenario_assets").fetchone()["count"] == 0

    adopted = service.adopt(
        "review-scenario",
        draft_id,
        preview_token=preview["preview_token"],
        data_url=preview["data_url"],
        adopted_by="admin",
    )

    assert adopted["binding"]["status"] == "confirmed"
    assert adopted["asset"]["visibility"] == "party"
    assert test_db.execute("SELECT COUNT(*) AS count FROM scenario_review_patches").fetchone()["count"] == 1


@pytest.mark.asyncio
async def test_missing_npc_item_and_clue_image_suggestions_remain_review_only(test_db, tmp_path):
    from src.server.scenario.scene_image_service import SceneImageError, SceneImageService

    class ImageGateway:
        async def suggest_scenario_images(self, context):
            assert [(target["target_type"], target["target_key"]) for target in context["targets"]] == [
                ("npc", "librarian"),
                ("item", "brass-key"),
                ("clue", "sealed-letter"),
            ]
            return {
                "summary": "三个缺图目标均可起草配图。",
                "suggestions": [
                    {
                        "target_type": "npc",
                        "target_key": "librarian",
                        "image_summary": "一位神情疲惫的图书管理员。",
                        "prompt": "1920 年代疲惫的图书管理员，无文字。",
                        "citation": {"source_part_id": "review-part-1"},
                        "confidence": 0.8,
                    },
                    {
                        "target_type": "item",
                        "target_key": "brass-key",
                        "image_summary": "一枚磨损的黄铜钥匙。",
                        "prompt": "磨损黄铜钥匙特写，无文字。",
                        "citation": {"source_part_id": "review-part-1"},
                        "confidence": 0.7,
                    },
                    {
                        "target_type": "clue",
                        "target_key": "sealed-letter",
                        "image_summary": "一封封蜡信。",
                        "prompt": "封蜡信件特写，无文字。",
                        "citation": {"source_part_id": "review-part-1"},
                        "confidence": 0.7,
                    },
                    {
                        "target_type": "clue",
                        "target_key": "sealed-letter",
                        "image_summary": "重复建议不应出现。",
                        "prompt": "重复提示词。",
                        "citation": {"source_part_id": "review-part-1"},
                        "confidence": 0.1,
                    },
                ],
            }

        async def generate_scene_image(self, context):
            raise AssertionError("该测试不应生成图片")

    _seed_review_version(test_db)
    from src.server.scenario.review_service import ScenarioReviewService

    draft = ScenarioReviewService(test_db).create_review_draft(
        "review-scenario",
        "review-v1",
        created_by="admin",
    )
    draft_id = draft["scenario_version_id"]
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps({
            "scenes": [{"scene_id": "study", "image_asset_id": "existing"}],
            "npcs": [{"npc_id": "librarian", "name": "图书管理员", "public_description": "疲惫的图书管理员。"}],
            "items": [{"item_id": "brass-key", "name": "黄铜钥匙"}],
            "clues": [{"clue_id": "sealed-letter", "name": "封蜡信", "public_description": "一封封蜡信。"}],
        }, ensure_ascii=False), draft_id),
    )
    test_db.commit()
    service = SceneImageService(test_db, gateway=ImageGateway(), asset_root=tmp_path)

    suggested = await service.suggest(
        "review-scenario",
        draft_id,
        target_types={"npc", "item", "clue"},
    )

    assert {(item["target_type"], item["target_key"]) for item in suggested["suggestions"]} == {
        ("npc", "librarian"),
        ("item", "brass-key"),
        ("clue", "sealed-letter"),
    }
    assert len(suggested["suggestions"]) == 3
    assert {item["visibility"] for item in suggested["suggestions"]} == {"host_only"}
    assert test_db.execute("SELECT COUNT(*) AS count FROM scenario_assets").fetchone()["count"] == 0

    with pytest.raises(SceneImageError, match="image_public_description_required"):
        await service.preview(
            "review-scenario",
            draft_id,
            suggestion={
                "target_type": "item",
                "target_key": "brass-key",
                "citation": {"source_part_id": "review-part-1"},
            },
            prompt="忽略我",
            visibility="party",
            size="1024x1024",
        )


@pytest.mark.asyncio
async def test_adopting_npc_image_binds_the_matching_npc_target(test_db, tmp_path):
    from src.server.scenario.scene_image_service import SceneImageService

    tiny_png = (
        "data:image/png;base64,"
        + base64.b64encode(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\x0dIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        ).decode("ascii")
    )

    class ImageGateway:
        async def generate_scene_image(self, context):
            return {"data_url": tiny_png, "mime_type": "image/png"}

    _seed_review_version(test_db)
    from src.server.scenario.review_service import ScenarioReviewService

    draft = ScenarioReviewService(test_db).create_review_draft(
        "review-scenario",
        "review-v1",
        created_by="admin",
    )
    draft_id = draft["scenario_version_id"]
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps({
            "npcs": [{"npc_id": "librarian", "name": "图书管理员", "public_description": "疲惫的图书管理员。"}],
        }, ensure_ascii=False), draft_id),
    )
    test_db.commit()
    service = SceneImageService(test_db, gateway=ImageGateway(), asset_root=tmp_path)

    preview = await service.preview(
        "review-scenario",
        draft_id,
        suggestion={
            "target_type": "npc",
            "target_key": "librarian",
            "citation": {"source_part_id": "review-part-1"},
        },
        prompt="疲惫的图书管理员，无文字。",
        visibility="host_only",
        size="1024x1024",
    )
    adopted = service.adopt(
        "review-scenario",
        draft_id,
        preview_token=preview["preview_token"],
        data_url=preview["data_url"],
        adopted_by="admin",
    )

    assert adopted["binding"]["target_type"] == "npc"
    assert adopted["binding"]["target_key"] == "librarian"
    patch = test_db.execute(
        "SELECT target_type, target_key, payload FROM scenario_review_patches WHERE review_patch_id = %s",
        (adopted["review_patch_id"],),
    ).fetchone()
    assert patch["target_type"] == "npc"
    assert patch["target_key"] == "librarian"
    payload = patch["payload"] if isinstance(patch["payload"], dict) else json.loads(patch["payload"])
    assert payload["npc_id"] == "librarian"


def test_review_workbench_api_is_admin_only_and_returns_source_parts(review_client, test_db):
    _seed_review_version(test_db)
    admin_token = _token(review_client, "reviewadmin")
    host_token = _token(review_client, "reviewhost")

    forbidden = review_client.get(
        "/api/scenarios/review-scenario/versions/review-v1/review-workbench",
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert forbidden.status_code == 403

    response = review_client.get(
        "/api/scenarios/review-scenario/versions/review-v1/review-workbench",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source_parts"][0]["page_number"] == 1
    assert any(issue["code"] == "missing_clues" for issue in payload["issues"])


def test_review_source_document_is_admin_only_and_served_from_storage(review_client, test_db, tmp_path):
    _seed_review_version(test_db)
    (tmp_path / "review.pdf").write_bytes(b"%PDF-test-source")
    app.state.scenario_storage_root = tmp_path
    admin_token = _token(review_client, "reviewadmin")
    host_token = _token(review_client, "reviewhost")

    forbidden = review_client.get(
        "/api/scenarios/review-scenario/versions/review-v1/review-sources/review-source",
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert forbidden.status_code == 403
    response = review_client.get(
        "/api/scenarios/review-scenario/versions/review-v1/review-sources/review-source",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.content == b"%PDF-test-source"


def test_review_api_creates_draft_applies_cited_patch_and_rebuilds(review_client, test_db):
    _seed_review_version(test_db)
    token = _token(review_client, "reviewadmin")
    headers = {"Authorization": f"Bearer {token}"}

    created = review_client.post(
        "/api/scenarios/review-scenario/versions/review-v1/review-drafts",
        headers=headers,
    )
    assert created.status_code == 200, created.text
    draft_id = created.json()["scenario_version_id"]

    patch = review_client.post(
        f"/api/scenarios/review-scenario/versions/{draft_id}/review-patches",
        headers=headers,
        json={
            "target_type": "clue",
            "target_key": "blood-envelope",
            "payload": {"clue_id": "blood-envelope", "name": "沾血的信封"},
            "provenance": "source",
            "citation": {"source_part_id": "review-part-1"},
        },
    )
    assert patch.status_code == 200, patch.text

    rebuilt = review_client.post(
        f"/api/scenarios/review-scenario/versions/{draft_id}/review-rebuild",
        headers=headers,
    )
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["quality_report"]["level"] == "ready"


def test_scene_image_suggestions_api_is_admin_only_and_has_no_asset_side_effect(review_client, test_db):
    class ImageGateway:
        async def suggest_scene_images(self, context):
            assert context["scenes"][0]["scene_id"] == "study"
            return {
                "summary": "书房可补充一张开场氛围图。",
                "suggestions": [{
                    "scene_id": "study",
                    "image_summary": "昏暗书房内散落着档案。",
                    "prompt": "1920 年代的昏暗书房，散落档案，无文字。",
                    "style": "painterly",
                    "citation": {"source_part_id": "review-part-1", "page_number": 1},
                    "confidence": 0.84,
                }],
            }

    _seed_review_version(test_db)
    admin_token = _token(review_client, "reviewadmin")
    host_token = _token(review_client, "reviewhost")
    created = review_client.post(
        "/api/scenarios/review-scenario/versions/review-v1/review-drafts",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200, created.text
    draft_id = created.json()["scenario_version_id"]
    previous_gateway = getattr(app.state, "gateway", None)
    app.state.gateway = ImageGateway()
    try:
        forbidden = review_client.post(
            f"/api/admin/scenarios/review-scenario/versions/{draft_id}/image-generations/suggestions",
            headers={"Authorization": f"Bearer {host_token}"},
        )
        response = review_client.post(
            f"/api/admin/scenarios/review-scenario/versions/{draft_id}/image-generations/suggestions",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    finally:
        app.state.gateway = previous_gateway

    assert forbidden.status_code == 403
    assert response.status_code == 200, response.text
    assert response.json()["suggestions"][0]["visibility"] == "host_only"
    assert test_db.execute("SELECT COUNT(*) AS count FROM scenario_assets").fetchone()["count"] == 0


def test_image_suggestions_api_accepts_non_scene_target_types(review_client, test_db):
    class ImageGateway:
        async def suggest_scenario_images(self, context):
            assert [(target["target_type"], target["target_key"]) for target in context["targets"]] == [
                ("npc", "librarian"),
            ]
            return {
                "summary": "图书管理员需要一张肖像。",
                "suggestions": [{
                    "target_type": "npc",
                    "target_key": "librarian",
                    "image_summary": "疲惫的图书管理员。",
                    "prompt": "1920 年代图书管理员肖像，无文字。",
                    "citation": {"source_part_id": "review-part-1"},
                    "confidence": 0.8,
                }],
            }

    _seed_review_version(test_db)
    admin_token = _token(review_client, "reviewadmin")
    created = review_client.post(
        "/api/scenarios/review-scenario/versions/review-v1/review-drafts",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200, created.text
    draft_id = created.json()["scenario_version_id"]
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps({"npcs": [{"npc_id": "librarian", "name": "图书管理员"}]}, ensure_ascii=False), draft_id),
    )
    test_db.commit()
    previous_gateway = getattr(app.state, "gateway", None)
    app.state.gateway = ImageGateway()
    try:
        response = review_client.post(
            f"/api/admin/scenarios/review-scenario/versions/{draft_id}/image-generations/suggestions",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"target_types": ["npc"]},
        )
    finally:
        app.state.gateway = previous_gateway

    assert response.status_code == 200, response.text
    assert response.json()["suggestions"][0]["target_type"] == "npc"
    assert response.json()["suggestions"][0]["target_key"] == "librarian"
