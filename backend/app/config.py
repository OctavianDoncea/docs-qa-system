from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = ROOT_DIR / '.env'

class Settings(BaseSettings):
    database_url: str
    ollama_url: str = 'http://localhost:11434'
    embedding_model: str
    api_key: str = ''
    groq_api_key: str = ''
    groq_llm_model: str = 'llama-3.1-8b-instant'
    llm_model: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    github_token: str = ''
    allowed_origins: str = 'http://localhost:5173, http://localhost:3000'
    confidence_threshold: float = 0.45
    rerank_enabled: bool = True
    rerank_candidates: int = 12

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding='utf-8', extra='ignore')

@lru_cache
def get_settings() -> Settings:
    return Settings()