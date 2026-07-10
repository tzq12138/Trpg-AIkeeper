import os


class Config:
    def __init__(
        self,
        provider: str = "deepseek",
        api_key: str = "",
        model: str = "deepseek-v4-pro",
        api_base: str = "https://api.deepseek.com",
        host: str = "0.0.0.0",
        port: int = 9100,
        log_level: str = "INFO",
    ):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.api_base = api_base
        self.host = host
        self.port = port
        self.log_level = log_level

    @classmethod
    def from_env(cls) -> "Config":
        explicit_provider = os.getenv("KP_MCP_PROVIDER", "").strip().lower()
        if explicit_provider in {"openai", "deepseek"}:
            provider = explicit_provider
        elif os.getenv("OPENAI_API_KEY", "").strip():
            provider = "openai"
        else:
            provider = "deepseek"

        if provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")
            model = os.getenv("OPENAI_MODEL", "gpt-5.4")
            api_base = (
                os.getenv("OPENAI_BASE_URL")
                or os.getenv("OPENAI_API_BASE")
                or "https://api.openai.com/v1"
            )
        else:
            api_key = os.getenv("DEEPSEEK_API_KEY", "")
            model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
            api_base = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")

        return cls(
            provider=provider,
            api_key=api_key,
            model=model,
            api_base=api_base,
            host=os.getenv("KP_MCP_HOST", "0.0.0.0"),
            port=int(os.getenv("KP_MCP_PORT", "9100")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )

    @property
    def is_mock(self) -> bool:
        return not self.api_key

    @property
    def deepseek_api_key(self) -> str:
        return self.api_key if self.provider == "deepseek" else ""

    @property
    def deepseek_model(self) -> str:
        return self.model if self.provider == "deepseek" else ""

    @property
    def deepseek_api_base(self) -> str:
        return self.api_base if self.provider == "deepseek" else ""
