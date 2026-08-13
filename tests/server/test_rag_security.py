"""Security tests for RAG search and indexing endpoints."""

import json
import pytest
from fastapi.testclient import TestClient
from src.server.main import app
from src.server.router_auth import _hash_password


@pytest.fixture
def client_with_data(test_db):
    from src.server.engine.engine import Engine
    c = TestClient(app)
    app.state.db = test_db
    app.state.engine = Engine(test_db)

    for aid, uname, role in [
        ("acc-admin", "admin", "admin"),
        ("acc-host", "raghost", "host"),
        ("acc-p1", "ragp1", "player"),
    ]:
        test_db.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (account_id) DO UPDATE SET role = %s",
            (aid, uname, _hash_password("test123"), uname, role, role),
        )
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, raw_text, import_status) "
        "VALUES ('rag-sc1', 'RAG Scenario', 'text', 'structured')"
    )
    test_db.execute(
        "INSERT INTO rooms (room_id, scenario_id, owner_token, owner_account_id, status) "
        "VALUES ('rag-room', 'rag-sc1', 'owntok', 'acc-host', 'lobby')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, account_id, status) "
        "VALUES ('rag-ch1', 'rag-room', 'Alice', 'ptok-rag', 'acc-p1', 'active')"
    )
    test_db.commit()
    return c


class TestRAGIndexAuth:
    def test_index_scenario_no_auth_returns_401(self, client_with_data):
        res = client_with_data.post("/api/rag/index", json={
            "scenario_id": "rag-sc1", "room_id": "rag-room",
        })
        assert res.status_code == 401

    def test_index_scenario_wrong_player_returns_403(self, client_with_data):
        # Player is in rag-room — let player try to index (write op)
        token = _login(client_with_data, "ragp1", "test123")
        res = client_with_data.post(
            "/api/rag/index",
            json={"scenario_id": "rag-sc1", "room_id": "rag-room"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # player cannot write/index — 403
        assert res.status_code == 403

    def test_host_cannot_index_a_different_scenario_into_owned_room(
        self, client_with_data, test_db
    ):
        test_db.execute(
            "INSERT INTO scenarios (scenario_id, title, raw_text, import_status) "
            "VALUES ('rag-sc-other', 'Other', 'secret', 'structured')"
        )

        class MockRag:
            called = False

            def index_scenario(self, *args, **kwargs):
                self.called = True
                return 1

        rag = MockRag()
        app.state.rag = rag
        token = _login(client_with_data, "raghost", "test123")
        response = client_with_data.post(
            "/api/rag/index",
            json={"scenario_id": "rag-sc-other", "room_id": "rag-room"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 409
        assert rag.called is False

    def test_legacy_index_endpoint_rejects_version_bound_room(
        self, client_with_data, test_db
    ):
        test_db.execute(
            "UPDATE rooms SET scenario_version_id = 'rag-sv-bound' WHERE room_id = 'rag-room'"
        )

        class MockRag:
            called = False

            def index_scenario(self, *args, **kwargs):
                self.called = True
                return 1

        rag = MockRag()
        app.state.rag = rag
        token = _login(client_with_data, "raghost", "test123")
        response = client_with_data.post(
            "/api/rag/index",
            json={"scenario_id": "rag-sc1", "room_id": "rag-room"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 409
        assert rag.called is False


class TestRAGSearchAuth:
    def test_search_no_auth_returns_401(self, client_with_data):
        res = client_with_data.post("/api/rag/search", json={
            "query": "test", "room_id": "rag-room",
        })
        assert res.status_code == 401

    def test_search_room_player_can_search(self, client_with_data):
        # Mock rag store on app state
        class MockRag:
            kwargs = None

            def search(self, *a, **kw):
                self.kwargs = kw
                return []
        rag = MockRag()
        app.state.rag = rag
        token = _login(client_with_data, "ragp1", "test123")
        res = client_with_data.post(
            "/api/rag/search",
            json={"query": "线索", "room_id": "rag-room"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Player in room can search
        assert res.status_code == 200
        assert rag.kwargs["audience"] == "player"

    def test_player_cannot_override_room_scenario_version(self, client_with_data):
        class MockRag:
            def search(self, *a, **kw):
                return []

        app.state.rag = MockRag()
        token = _login(client_with_data, "ragp1", "test123")
        res = client_with_data.post(
            "/api/rag/search",
            json={
                "query": "线索",
                "room_id": "rag-room",
                "scenario_version_id": "sv-other",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert res.status_code == 403

    def test_player_cannot_override_room_rule_version(self, client_with_data):
        class MockRag:
            def search(self, *a, **kw):
                return []

        app.state.rag = MockRag()
        token = _login(client_with_data, "ragp1", "test123")
        res = client_with_data.post(
            "/api/rag/search",
            json={
                "query": "奖励骰",
                "room_id": "rag-room",
                "rule_set_version_id": "rules-other",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert res.status_code == 403

    def test_admin_can_debug_an_explicit_scenario_version(self, client_with_data):
        class MockRag:
            kwargs = None

            def search(self, *a, **kw):
                self.kwargs = kw
                return []

        rag = MockRag()
        app.state.rag = rag
        token = _login(client_with_data, "admin", "test123")
        res = client_with_data.post(
            "/api/rag/search",
            json={"query": "真相", "scenario_version_id": "sv-1"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert res.status_code == 200
        assert rag.kwargs["audience"] == "admin"
        assert rag.kwargs["scenario_version_id"] == "sv-1"

    def test_search_wrong_room_returns_403(self, client_with_data, test_db):
        # Create another room that the player is NOT in
        test_db.execute(
            "INSERT INTO rooms (room_id, scenario_id, owner_token, owner_account_id, status) "
            "VALUES ('rag-room2', 'rag-sc1', 'tok2', 'acc-admin', 'lobby')"
        )
        test_db.commit()
        token = _login(client_with_data, "ragp1", "test123")
        res = client_with_data.post(
            "/api/rag/search",
            json={"query": "线索", "room_id": "rag-room2"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403


class TestRuleDocs:
    def test_rule_docs_no_auth_returns_401(self, client_with_data):
        res = client_with_data.get("/api/rag/rule-docs")
        assert res.status_code == 401

    def test_rule_docs_with_auth_returns_ok(self, client_with_data):
        token = _login(client_with_data, "admin", "test123")
        res = client_with_data.get(
            "/api/rag/rule-docs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200

    def test_rule_docs_are_not_available_to_a_host(self, client_with_data):
        token = _login(client_with_data, "raghost", "test123")

        res = client_with_data.get(
            "/api/rag/rule-docs",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert res.status_code == 403


class TestRAGHostAdmin:
    def test_index_as_host_succeeds(self, client_with_data):
        """Host (room owner) can index their own room."""
        class MockRagFull:
            def index_scenario(self, *a, **kw): return {"indexed": 0}
        app.state.rag = MockRagFull()
        token = _login(client_with_data, "raghost", "test123")
        res = client_with_data.post(
            "/api/rag/index",
            json={"scenario_id": "rag-sc1", "room_id": "rag-room"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200

    def test_index_as_admin_succeeds(self, client_with_data):
        """Admin can index any room."""
        class MockRagFull:
            def index_scenario(self, *a, **kw): return {"indexed": 0}
        app.state.rag = MockRagFull()
        token = _login(client_with_data, "admin", "test123")
        res = client_with_data.post(
            "/api/rag/index",
            json={"scenario_id": "rag-sc1", "room_id": "rag-room"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200

    def test_search_as_host_succeeds(self, client_with_data):
        """Host (room owner) can search their room."""
        class MockRagSearch:
            kwargs = None

            def search(self, *a, **kw):
                self.kwargs = kw
                return []

        rag = MockRagSearch()
        app.state.rag = rag
        token = _login(client_with_data, "raghost", "test123")
        res = client_with_data.post(
            "/api/rag/search",
            json={"query": "test", "room_id": "rag-room"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        assert rag.kwargs["audience"] == "host"

    def test_host_search_only_returns_excerpt_and_auditable_citation(self, client_with_data):
        class MockRagSearch:
            def search(self, *args, **kwargs):
                return [{
                    "chunk_id": "chunk-secret",
                    "source_type": "rule",
                    "source_id": "rule-doc",
                    "content": "完整规则原文不应下发给 Host。" * 30,
                    "metadata": {"internal_note": "secret"},
                    "score": 0.9,
                    "citation": {
                        "chunk_id": "chunk-secret",
                        "source_ref": "coc7-srd#page=4",
                        "excerpt": "奖励骰取较低的完整百分骰结果。",
                        "full_text": "不可下发的完整规则" * 200,
                    },
                }]

        app.state.rag = MockRagSearch()
        token = _login(client_with_data, "raghost", "test123")
        response = client_with_data.post(
            "/api/rag/search",
            json={"query": "奖励骰", "room_id": "rag-room"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        result = response.json()[0]
        assert result["content"] == "奖励骰取较低的完整百分骰结果。"
        assert "metadata" not in result
        assert result["citation"]["source_ref"] == "coc7-srd#page=4"
        assert "full_text" not in result["citation"]

    def test_admin_search_keeps_full_debug_payload(self, client_with_data):
        class MockRagSearch:
            def search(self, *args, **kwargs):
                return [{
                    "chunk_id": "chunk-admin",
                    "source_type": "rule",
                    "source_id": "rule-doc",
                    "content": "full content",
                    "metadata": {"category": "checks"},
                    "citation": {"excerpt": "summary"},
                    "score": 0.8,
                }]

        app.state.rag = MockRagSearch()
        token = _login(client_with_data, "admin", "test123")
        response = client_with_data.post(
            "/api/rag/search",
            json={"query": "奖励骰"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json()[0]["content"] == "full content"
        assert response.json()[0]["metadata"] == {"category": "checks"}


class TestRAGVersionRebuild:
    def test_admin_rebuilds_only_sources_bound_to_requested_version(
        self, client_with_data, test_db
    ):
        test_db.execute(
            """
            INSERT INTO scenario_versions (
                scenario_version_id, scenario_id, version_number, status,
                knowledge_graph, quality_report, prep_package, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("rag-sv1", "rag-sc1", 1, "draft", "{}", "{}", "{}", "acc-admin"),
        )
        test_db.execute(
            """
            INSERT INTO source_documents (
                source_document_id, scenario_id, source_kind, title, source_filename,
                mime_type, source_sha256, storage_path, license_type, status, metadata,
                created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rag-doc1", "rag-sc1", "scenario", "测试模组", "module.pdf",
                "application/pdf", "rag-sha1", "managed/rag-doc1", "authorized",
                "ready", "{}", "acc-admin",
            ),
        )
        test_db.execute(
            """
            INSERT INTO source_parts (
                source_part_id, source_document_id, ordinal, part_kind, page_number,
                text_content, mime_type, anchor, checksum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rag-part1", "rag-doc1", 1, "page", 4, "钟楼地下室有黑色钥匙。",
                "text/plain", '{"page": 4}', "rag-checksum1",
            ),
        )
        test_db.execute(
            """
            INSERT INTO scenario_version_sources (
                scenario_version_id, source_document_id, ordinal
            ) VALUES (?, ?, ?)
            """,
            ("rag-sv1", "rag-doc1", 1),
        )

        class MockRag:
            call = None

            class embedding:
                model_name = "local-v1"
                dimension = 768

            def index_scenario_version(self, *args, **kwargs):
                self.call = (args, kwargs)
                self.embedding.model_name = "remote-v2"
                self.embedding.dimension = 1536
                return len(args[2])

        rag = MockRag()
        app.state.rag = rag
        token = _login(client_with_data, "admin", "test123")
        response = client_with_data.post(
            "/api/admin/rag/reindex-version",
            json={"scenario_version_id": "rag-sv1"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "complete"
        assert body["chunks_indexed"] == 1
        assert rag.call[0][0:2] == ("rag-sc1", "rag-sv1")
        assert rag.call[0][2][0]["source_part_id"] == "rag-part1"
        assert rag.call[0][2][0]["source_ref"] == "module.pdf#page=4"
        rebuild = test_db.execute(
            "SELECT status, chunk_count, embedding_model, embedding_dimensions "
            "FROM rag_rebuild_records WHERE rebuild_id = ?",
            (body["rebuild_id"],),
        ).fetchone()
        version = test_db.execute(
            "SELECT rag_index_version FROM scenario_versions WHERE scenario_version_id = ?",
            ("rag-sv1",),
        ).fetchone()
        assert rebuild["status"] == "complete"
        assert rebuild["chunk_count"] == 1
        assert rebuild["embedding_model"] == "remote-v2"
        assert rebuild["embedding_dimensions"] == 1536
        assert version["rag_index_version"] == body["rebuild_id"]

    def test_non_admin_cannot_rebuild_version(self, client_with_data):
        token = _login(client_with_data, "raghost", "test123")

        response = client_with_data.post(
            "/api/admin/rag/reindex-version",
            json={"scenario_version_id": "missing"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403


class TestRuleSetLifecycle:
    def test_admin_creates_indexes_publishes_and_host_binds_rule_version(
        self, client_with_data, test_db
    ):
        admin_token = _login(client_with_data, "admin", "test123")
        created = client_with_data.post(
            "/api/rag/rule-sets",
            json={
                "name": "CoC7 Open Rules",
                "slug": "coc7-open-rules",
                "system": "coc7",
                "description": "Open licensed core rules",
                "license_type": "open",
                "is_base": True,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert created.status_code == 200, created.text
        rule_set_id = created.json()["rule_set_id"]

        version_response = client_with_data.post(
            f"/api/rag/rule-sets/{rule_set_id}/versions",
            json={"label": "7e-v1", "source_sha256": "rules-source-sha"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert version_response.status_code == 200, version_response.text
        rule_set_version_id = version_response.json()["rule_set_version_id"]

        class MockRag:
            kwargs = None

            def index_rules(self, *args, **kwargs):
                self.kwargs = kwargs
                return 2

        rag = MockRag()
        app.state.rag = rag
        indexed = client_with_data.post(
            "/api/rag/index-rules",
            json={
                "doc_id": "coc7-checks",
                "rule_set_version_id": rule_set_version_id,
                "title": "技能检定",
                "category": "checks",
                "content": "奖励骰取较低结果。惩罚骰取较高结果。",
                "source_ref": "coc7-srd#checks",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert indexed.status_code == 200, indexed.text
        assert indexed.json()["chunks"] == 2
        assert rag.kwargs["rule_set_version_id"] == rule_set_version_id
        assert rag.kwargs["license_type"] == "open"
        assert rag.kwargs["visibility"] == "host_only"

        published = client_with_data.post(
            f"/api/rag/rule-set-versions/{rule_set_version_id}/publish",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert published.status_code == 200, published.text

        immutable = client_with_data.post(
            "/api/rag/index-rules",
            json={
                "doc_id": "coc7-checks",
                "rule_set_version_id": rule_set_version_id,
                "title": "篡改",
                "category": "checks",
                "content": "已发布内容不应被覆盖",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert immutable.status_code == 409

        test_db.execute(
            "INSERT INTO scenario_versions (scenario_version_id, scenario_id, version_number, "
            "status, created_by) VALUES (?, ?, ?, ?, ?)",
            ("rag-policy-sv", "rag-sc1", 1, "draft", "acc-admin"),
        )
        scenario_binding = client_with_data.post(
            "/api/rag/rule-bindings/scenarios/rag-policy-sv",
            json={"rule_set_version_id": rule_set_version_id, "priority": 10},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert scenario_binding.status_code == 200, scenario_binding.text
        assert test_db.execute(
            "SELECT priority FROM scenario_rule_bindings WHERE scenario_version_id = ? "
            "AND rule_set_version_id = ?",
            ("rag-policy-sv", rule_set_version_id),
        ).fetchone()["priority"] == 10

        host_token = _login(client_with_data, "raghost", "test123")
        bound = client_with_data.post(
            "/api/rag/rule-bindings/rooms/rag-room",
            json={"rule_set_version_id": rule_set_version_id, "priority": 250},
            headers={"Authorization": f"Bearer {host_token}"},
        )
        assert bound.status_code == 200, bound.text
        binding = test_db.execute(
            "SELECT priority FROM room_rule_bindings "
            "WHERE room_id = ? AND rule_set_version_id = ?",
            ("rag-room", rule_set_version_id),
        ).fetchone()
        assert binding["priority"] == 250
        test_db.execute(
            "INSERT INTO host_states (room_id, state) VALUES ('rag-room', ?) "
            "ON CONFLICT (room_id) DO UPDATE SET state = EXCLUDED.state",
            (json.dumps({"ai_config": {"runtime_binding": {"locked": True}}}),),
        )

        rejected_change = client_with_data.post(
            "/api/rag/rule-bindings/rooms/rag-room",
            json={"rule_set_version_id": rule_set_version_id, "priority": 300},
            headers={"Authorization": f"Bearer {host_token}"},
        )

        assert rejected_change.status_code == 409
        assert rejected_change.json()["detail"] == "房间规则运行版本已固定，不能静默切换"
        assert test_db.execute(
            "SELECT priority FROM room_rule_bindings "
            "WHERE room_id = ? AND rule_set_version_id = ?",
            ("rag-room", rule_set_version_id),
        ).fetchone()["priority"] == 250

    def test_rule_set_rejects_unverified_license(self, client_with_data):
        token = _login(client_with_data, "admin", "test123")

        response = client_with_data.post(
            "/api/rag/rule-sets",
            json={
                "name": "Unknown Copyright",
                "slug": "unknown-copyright",
                "system": "coc7",
                "license_type": "unknown",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 400

    def test_publishing_new_rule_version_supersedes_previous_version(
        self, client_with_data, test_db
    ):
        admin_token = _login(client_with_data, "admin", "test123")
        created = client_with_data.post(
            "/api/rag/rule-sets",
            json={
                "name": "Versioned CoC7 Rules",
                "slug": "versioned-coc7-rules",
                "system": "coc7",
                "license_type": "open",
                "is_base": True,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        rule_set_id = created.json()["rule_set_id"]
        version_ids = []
        for label in ("v1", "v2"):
            version = client_with_data.post(
                f"/api/rag/rule-sets/{rule_set_id}/versions",
                json={"label": label},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            version_ids.append(version.json()["rule_set_version_id"])

        for rule_set_version_id in version_ids:
            published = client_with_data.post(
                f"/api/rag/rule-set-versions/{rule_set_version_id}/publish",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert published.status_code == 200, published.text

        rows = test_db.execute(
            "SELECT rule_set_version_id, status FROM rule_set_versions "
            "WHERE rule_set_id = ? ORDER BY version_number",
            (rule_set_id,),
        ).fetchall()
        assert [(row["rule_set_version_id"], row["status"]) for row in rows] == [
            (version_ids[0], "superseded"),
            (version_ids[1], "published"),
        ]

    def test_non_admin_cannot_create_rule_set(self, client_with_data):
        token = _login(client_with_data, "raghost", "test123")

        response = client_with_data.post(
            "/api/rag/rule-sets",
            json={
                "name": "House Rules",
                "slug": "house-rules",
                "system": "coc7",
                "license_type": "authorized",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403


def _login(client, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={
        "username": username, "password": password,
    })
    assert res.status_code == 200, f"Login failed: {res.text}"
    return res.json()["token"]
