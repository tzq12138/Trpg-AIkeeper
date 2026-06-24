import os
from pydantic import BaseModel


class Settings(BaseModel):
    database_url: str = "postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-pro"
    host: str = "0.0.0.0"
    port: int = 3001

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", "postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper"),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "3001")),
        )
