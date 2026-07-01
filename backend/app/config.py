from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = ROOT_DIR / '.env'

class Settings(BaseSettings):
    database_url: str
    google_api_key: str = ''
    embedding_model: str = 'gemini-embedding-001'
    ollama_url: str = 'http://localhost:11434'
    groq_api_key: str = ''
    groq_llm_model: str = 'llama-3.1-8b-instant'
    llm_model: str = 'llama-3.1-8b-instant'
    chunk_size: int = 1500
    chunk_overlap: int = 200
    top_k: int = 5
    confidence_threshold: float = 0.45
    rerank_enabled: bool = True
    rerank_candidates: int = 12
    api_key: str = ''
    github_token: str = ''
    allowed_origins: str = 'http://localhost:5173,http://localhost:3000'

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding='utf-8', extra='ignore')

@lru_cache
def get_settings() -> Settings:
    return Settings()