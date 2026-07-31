from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    OPENAI_API_KEY: str = "demo"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_PROVIDER: str = "openai"
    # Endpoint OpenAI-compatible. Si se setea (ej. servidor local), se usa ese
    # en vez de api.openai.com y NO hace falta API key real (se manda una dummy).
    LLM_BASE_URL: Optional[str] = None
    ARTIFACT_DIR: str = "./artifacts"
    SIMILARITY_THRESHOLD: float = 0.85
    TOKEN_COST_INPUT: float = 0.00015
    TOKEN_COST_OUTPUT: float = 0.0006
    RUST_ENGINE_PATH: Optional[str] = None
    MAX_EXECUTION_TIMEOUT: int = 30
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8080

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
