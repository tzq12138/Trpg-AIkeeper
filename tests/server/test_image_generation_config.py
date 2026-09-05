import base64
import json
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.server.main import app
from src.server.router_auth import _hash_password


def _image_config_payload(**overrides):
    payload = {
        "name": "Scenario Art",
        "api_base_url": "https://images.example.com/v1",
        "model": "gpt-image-1",
        "api_key": "sk-image-secret-1234",
        "default_size": "1024x1024",
    }
    payload.update(overrides)
    return payload


def test_image_generation_config_encrypts_key_and_returns_only_masked_metadata(test_db):
    from src.server.ai.image_generation import ImageGenerationConfigStore
    from src.server.ai.provider_config import SecretCipher

    store = ImageGenerationConfigStore(test_db, SecretCipher("master-secret"))
    created = store.create(_image_config_payload(), actor_id="admin-1")

    stored = test_db.execute(
        "SELECT api_key_ciphertext FROM image_generation_configs "
        "WHERE image_generation_config_id = %s",
        (created["image_generation_config_id"],),
    ).fetchone()

    assert "sk-image-secret-1234" not in str(created)
    assert "api_key_ciphertext" not in created
    assert created["has_api_key"] is True
    assert created["key_mask"] == "••••1234"
    assert "sk-image-secret-1234" not in stored["api_key_ciphertext"]
    assert store.get_secret(created["image_generation_config_id"]) == "sk-image-secret-1234"


class _FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._data


class _RecordingClient:
    requests = []
    response = None

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, **kwargs):
        self.requests.append({"url": url, "client": self.kwargs, **kwargs})
        return self.response


@pytest.mark.asyncio
async def test_image_generation_provider_uses_safe_base64_response(monkeypatch):
    from src.server.ai.image_generation import ImageGenerationProvider

    image_bytes = b"\x89PNG\r\n\x1a\nexample-image"
    _RecordingClient.requests = []
    _RecordingClient.response = _FakeResponse({
        "data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}],
    })
    monkeypatch.setattr("src.server.ai.image_generation.httpx.AsyncClient", _RecordingClient)
    provider = ImageGenerationProvider({
        "api_base_url": "http://127.0.0.1:9999/v1",
        "model": "gpt-image-1",
        "api_key": "sk-image-secret-1234",
        "default_size": "1024x1024",
    })

    result = await provider.generate("阴雨中的海港调查所", size="1024x1024")

    request = _RecordingClient.requests[0]
    assert request["url"] == "http://127.0.0.1:9999/v1/images/generations"
    assert request["client"]["follow_redirects"] is False
    assert request["json"] == {
        "model": "gpt-image-1",
        "prompt": "阴雨中的海港调查所",
        "size": "1024x1024",
        "response_format": "b64_json",
    }
    assert result["content"] == image_bytes
    assert result["mime_type"] == "image/png"


def test_admin_saves_masked_image_provider_and_must_test_before_activation(test_db):
    client = TestClient(app)
    app.state.db = test_db
    test_db.execute(
        """
        INSERT INTO accounts (account_id, username, password_hash, display_name, role)
        VALUES ('image-admin', 'imageadmin', %s, 'Image Admin', 'admin')
        """,
        (_hash_password("test123"),),
    )
    test_db.commit()
    token = client.post("/api/auth/login", json={
        "username": "imageadmin",
        "password": "test123",
    }).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/api/admin/ai/image-providers",
        json=_image_config_payload(),
        headers=headers,
    )

    assert created.status_code == 200
    body = created.json()
    assert body["key_mask"] == "••••1234"
    assert "api_key_ciphertext" not in body
    assert "sk-image-secret-1234" not in created.text

    activation = client.post(
        f"/api/admin/ai/image-providers/{body['image_generation_config_id']}/activate",
        headers=headers,
    )
    assert activation.status_code == 409
    assert activation.json()["detail"] == "provider_test_required"


def test_generated_scene_image_needs_explicit_bind_before_review_draft_changes(
    test_db,
    monkeypatch,
):
    from src.server.ai.image_generation import ImageGenerationConfigStore

    client = TestClient(app)
    app.state.db = test_db
    test_db.execute(
        """
        INSERT INTO accounts (account_id, username, password_hash, display_name, role)
        VALUES ('scene-image-admin', 'sceneimageadmin', %s, 'Scene Image Admin', 'admin')
        """,
        (_hash_password("test123"),),
    )
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title) VALUES ('image-scenario', '图片审核')"
    )
    test_db.execute(
        """
        INSERT INTO scenario_versions (
            scenario_version_id, scenario_id, version_number, status, knowledge_graph, created_by
        ) VALUES ('image-parent-v1', 'image-scenario', 1, 'draft_ready', %s, 'scene-image-admin')
        """,
        ('{"scenes":[{"scene_id":"harbor","name":"雨港"}],"npcs":[{"npc_id":"keeper","name":"守夜人"}]}',),
    )
    test_db.execute(
        """
        INSERT INTO scenario_versions (
            scenario_version_id, scenario_id, version_number, status, knowledge_graph, created_by
        ) VALUES ('image-review-v2', 'image-scenario', 2, 'draft_review', %s, 'scene-image-admin')
        """,
        ('{"scenes":[{"scene_id":"harbor","name":"雨港"}],"npcs":[{"npc_id":"keeper","name":"守夜人"}]}',),
    )
    test_db.execute(
        """
        INSERT INTO scenario_review_drafts (scenario_version_id, parent_version_id, created_by)
        VALUES ('image-review-v2', 'image-parent-v1', 'scene-image-admin')
        """
    )
    test_db.commit()
    monkeypatch.setenv("AI_CONFIG_MASTER_KEY", "master-secret")
    store = ImageGenerationConfigStore(test_db)
    config = store.create(_image_config_payload(), actor_id="scene-image-admin")
    store.record_test(config["image_generation_config_id"], True, 1, "scene-image-admin")
    store.activate(config["image_generation_config_id"], "scene-image-admin")
    test_db.commit()
    asset_root = Path(tempfile.mkdtemp(prefix="aikeeper-image-generation-"))
    monkeypatch.setattr("src.server.router_admin.ASSETS_ROOT", asset_root)

    async def generate(_self, _prompt, size=None):
        return {
            "content": b"\x89PNG\r\n\x1a\nscene-image",
            "mime_type": "image/png",
            "latency_ms": 12,
        }

    monkeypatch.setattr("src.server.ai.image_generation.ImageGenerationProvider.generate", generate)
    token = client.post("/api/auth/login", json={
        "username": "sceneimageadmin",
        "password": "test123",
    }).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    try:
        optimized = client.post(
            "/api/admin/scenarios/image-scenario/versions/image-review-v2/"
            "image-generations/optimize-prompt",
            headers=headers,
            json={
                "target_type": "scene",
                "target_key": "harbor",
                "prompt": "雨夜的海港调查所，潮湿石板路",
                "effect": "低饱和手绘恐怖风格，无文字",
            },
        )

        assert optimized.status_code == 200, optimized.text
        assert "雨港" in optimized.json()["final_prompt"]
        assert test_db.execute(
            "SELECT count(*) AS count FROM scenario_image_generations"
        ).fetchone()["count"] == 0

        generated = client.post(
            "/api/admin/scenarios/image-scenario/versions/image-review-v2/image-generations",
            headers=headers,
            json={
                "target_type": "scene",
                "target_key": "harbor",
                "prompt": "雨夜的海港调查所，潮湿石板路",
                "effect": "低饱和手绘恐怖风格，无文字",
            },
        )

        assert generated.status_code == 200, generated.text
        generation = generated.json()
        assert generation["status"] == "generated"
        assert test_db.execute(
            "SELECT count(*) AS count FROM scenario_review_patches WHERE scenario_version_id = 'image-review-v2'"
        ).fetchone()["count"] == 0
        assert (asset_root / "image-scenario").exists()

        manually_bound = client.post(
            "/api/admin/scenarios/image-scenario/versions/image-review-v2/"
            "image-generations/bind-asset",
            headers=headers,
            json={
                "target_type": "npc",
                "target_key": "keeper",
                "asset_id": generation["asset_id"],
                "confirm": True,
            },
        )

        assert manually_bound.status_code == 200, manually_bound.text
        assert manually_bound.json()["status"] == "bound"

        bound = client.post(
            "/api/admin/scenarios/image-scenario/versions/image-review-v2/"
            f"image-generations/{generation['generation_id']}/bind",
            headers=headers,
            json={"confirm": True},
        )

        assert bound.status_code == 200, bound.text
        patch = test_db.execute(
            "SELECT target_type, target_key, payload FROM scenario_review_patches "
            "WHERE scenario_version_id = 'image-review-v2' AND target_key = 'harbor'"
        ).fetchone()
        assert patch["target_type"] == "scene"
        assert patch["target_key"] == "harbor"
        assert patch["payload"]["image_asset_id"] == generation["asset_id"]
    finally:
        shutil.rmtree(asset_root, ignore_errors=True)


def test_quality_report_accepts_scene_asset_binding_as_illustration():
    from src.server.scenario.quality import QualityReportGenerator

    report = QualityReportGenerator().evaluate({
        "scenes": [{
            "scene_id": "harbor",
            "name": "雨港",
            "image_asset_id": "generated-harbor-art",
        }],
        "npcs": [{"npc_id": "keeper", "name": "守夜人"}],
        "clues": [{"clue_id": "letter", "name": "潮湿信件"}],
        "truth": {"summary": "失踪案与灯塔有关"},
        "endings": [{"ending_id": "escape", "name": "离开雨港"}],
        "spoiler_boundaries": [{"id": "truth", "level": "keeper"}],
    })

    assert all(issue.code != "scene_images_missing" for issue in report.issues)


def test_party_visible_scene_image_uses_public_description_only(test_db, monkeypatch, tmp_path):
    from src.server.ai.image_generation import ImageGenerationConfigStore

    client = TestClient(app)
    app.state.db = test_db
    test_db.execute(
        "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
        "VALUES ('party-image-admin', 'partyimageadmin', %s, 'Party Image Admin', 'admin')",
        (_hash_password("test123"),),
    )
    test_db.execute("INSERT INTO scenarios (scenario_id, title) VALUES ('party-image-scenario', '队伍图片')")
    test_db.execute(
        """
        INSERT INTO scenario_versions (
            scenario_version_id, scenario_id, version_number, status, knowledge_graph, created_by
        ) VALUES ('party-image-review', 'party-image-scenario', 1, 'draft_review', %s, 'party-image-admin')
        """,
        (json.dumps({"scenes": [{
            "scene_id": "basement",
            "name": "地下室",
            "description": "凶手正在地下室举行召唤仪式。",
            "public_description": "潮湿阴冷的旧地下室，散落着木箱和水渍。",
        }]}),),
    )
    test_db.execute(
        "INSERT INTO scenario_review_drafts (scenario_version_id, parent_version_id, created_by) "
        "VALUES ('party-image-review', 'party-image-review', 'party-image-admin')"
    )
    test_db.commit()
    monkeypatch.setenv("AI_CONFIG_MASTER_KEY", "master-secret")
    config = ImageGenerationConfigStore(test_db).create(_image_config_payload(), actor_id="party-image-admin")
    ImageGenerationConfigStore(test_db).record_test(config["image_generation_config_id"], True, 1, "party-image-admin")
    ImageGenerationConfigStore(test_db).activate(config["image_generation_config_id"], "party-image-admin")

    captured: list[str] = []

    async def generate(_self, prompt, size=None):
        captured.append(prompt)
        return {"content": b"\x89PNG\r\n\x1a\nparty", "mime_type": "image/png", "latency_ms": 1}

    monkeypatch.setattr("src.server.ai.image_generation.ImageGenerationProvider.generate", generate)
    monkeypatch.setattr("src.server.router_admin.ASSETS_ROOT", tmp_path)
    token = client.post("/api/auth/login", json={"username": "partyimageadmin", "password": "test123"}).json()["token"]
    response = client.post(
        "/api/admin/scenarios/party-image-scenario/versions/party-image-review/image-generations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "scene",
            "target_key": "basement",
            "prompt": "画出凶手正在地下室举行召唤仪式。",
            "effect": "低饱和手绘",
            "visibility": "party",
        },
    )

    assert response.status_code == 200, response.text
    assert "潮湿阴冷的旧地下室" in captured[0]
    assert "凶手" not in captured[0]
    assert "召唤仪式" not in captured[0]
