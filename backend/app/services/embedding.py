import logging
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

async def initialize() -> None:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(f'{settings.ollama_url}/api/embed', json={'model': settings.embedding_model, 'input': 'ping'})
            response.raise_for_status()
            logger.info(f'Model {settings.embedding_model} is ready via Ollama.')
        except httpx.ConnectError:
            raise RuntimeError(f'Cannot connect to Ollama at {settings.ollama_url}. Start it with: ollama serve')
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise RuntimeError(f"Model '{settings.embedding_model}' not found in Ollama. Pull it first: ollama pull {settings.embedding_model}")
            raise

async def encode_documents(texts: list[str]) -> list[list[float]]:
    return await _embed(texts)

async def encode_query(text: str) -> list[float]:
    results = await _embed([text])
    return results[0]

async def _embed(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f'{settings.ollama_url}/api/embed', json={'model': settings.embedding_model, 'input': texts})
        resp.raise_for_status()
        return resp.json()['embeddings']