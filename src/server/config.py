import os
from pydantic import BaseModel


class Settings(BaseModel):
    database_url: str = "postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-pro"
    host: str = "0.0.0.0"
    port: int = 3001
    agent_enabled: bool = False
    redis_url: str = ""
    kp_mcp_server_url: str = "http://127.0.0.1:9100/mcp"
    ai_provider_order: str = "mcp,deepseek,local"
    ai_timeout_seconds: int = 30
    stt_provider: str = "disabled"
    stt_http_url: str = ""
    stt_http_api_key: str = ""
    log_level: str = "INFO"
    log_file: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", "postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper"),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "3001")),
            agent_enabled=os.getenv("AGENT_ENABLED", "").lower() in ("1", "true", "yes"),
            redis_url=os.getenv("REDIS_URL", ""),
            kp_mcp_server_url=os.getenv("KP_MCP_SERVER_URL", "http://127.0.0.1:9100/mcp"),
            ai_provider_order=os.getenv("AI_PROVIDER_ORDER", "deepseek,mcp,local"),
            ai_timeout_seconds=int(os.getenv("AI_TIMEOUT_SECONDS", "30")),
            stt_provider=os.getenv("STT_PROVIDER", "disabled"),
            stt_http_url=os.getenv("STT_HTTP_URL", ""),
            stt_http_api_key=os.getenv("STT_HTTP_API_KEY", ""),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=os.getenv("LOG_FILE", ""),
        )
