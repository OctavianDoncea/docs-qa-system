from functools import lru_cache
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    ollama_url: str
    embedding_model: str
    groq_api_key: str
    llm_model: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    github_token: str

    model_config = {'env_file': '.env', 'env_file_encoding': 'utf-8'}

@lru_cache
def get_settings() -> Settings:
    return Settings()