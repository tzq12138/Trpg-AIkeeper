import json

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
        "spoiler_boundaries": [{"id": "truth", "level": "keeper"}],
    })

    issue = next(item for item in report.issues if item.code == "missing_clues")

    assert issue.blocking is True
    assert issue.target_type == "clue"
    assert issue.resolution_hint == "补充至少一条可发现的线索"


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
        "spoiler_boundaries": [{"id": "truth", "level": "keeper"}],
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
