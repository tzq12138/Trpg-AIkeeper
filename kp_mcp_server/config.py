import os

class Config:
    def __init__(
        self,
        deepseek_api_key: str = "",
        deepseek_model: str = "deepseek-v4-pro",
        deepseek_api_base: str = "https://api.deepseek.com",
        host: str = "0.0.0.0",
        port: int = 9100,
        log_level: str = "INFO",
    ):
        self.deepseek_api_key = deepseek_api_key
        self.deepseek_model = deepseek_model
        self.deepseek_api_base = deepseek_api_base
        self.host = host
        self.port = port
        self.log_level = log_level

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            deepseek_api_base=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
            host=os.getenv("KP_MCP_HOST", "0.0.0.0"),
            port=int(os.getenv("KP_MCP_PORT", "9100")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )

    @property
    def is_mock(self) -> bool:
        return not self.deepseek_api_key
