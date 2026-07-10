from kp_mcp_server.config import Config


def test_kp_mcp_config_prefers_openai_when_key_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4")
    monkeypatch.delenv("KP_MCP_PROVIDER", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    config = Config.from_env()

    assert config.provider == "openai"
    assert config.api_key == "sk-openai"
    assert config.model == "gpt-5.4"


def test_kp_mcp_config_can_stay_on_deepseek(monkeypatch):
    monkeypatch.setenv("KP_MCP_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    config = Config.from_env()

    assert config.provider == "deepseek"
    assert config.api_key == "sk-deepseek"
    assert config.model == "deepseek-v4-pro"
