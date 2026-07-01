import logging
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

# text-embedding-004 was shut down by Google on 2026-01-14; gemini-embedding-001
# is the current GA replacement (same v1beta batchEmbedContents endpoint).
_EMBED_MODEL = 'gemini-embedding-001'
_EMBED_URL = (
    'https://generativelanguage.googleapis.com'
    f'/v1beta/models/{_EMBED_MODEL}:batchEmbedContents'
)
_BATCH_SIZE = 100   # Gemini free tier batch limit


async def initialize() -> None:
    settings = get_settings()
    if not settings.google_api_key:
        raise RuntimeError('GOOGLE_API_KEY is not set. Get a free key at https://ai.google.dev')
    try:
        await encode_query('ping')
        logger.info('Google Gemini embedding API ready.')
    except Exception as exc:
        raise RuntimeError(f'Gemini API check failed: {exc}') from exc


async def encode_documents(texts: list[str]) -> list[list[float]]:
    """Embed document/passage strings for storage in pgvector."""
    return await _embed(texts, task_type='RETRIEVAL_DOCUMENT')


async def encode_query(text: str) -> list[float]:
    """Embed a single search query for retrieval."""
    results = await _embed([text], task_type='RETRIEVAL_QUERY')
    return results[0]


async def _embed(texts: list[str], task_type: str) -> list[list[float]]:
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        all_embeddings.extend(await _call_api(batch, task_type))
    return all_embeddings


async def _call_api(texts: list[str], task_type: str) -> list[list[float]]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            _EMBED_URL,
            headers={'x-goog-api-key': settings.google_api_key},
            json={
                'requests': [
                    {
                        'model': f'models/{_EMBED_MODEL}',
                        'content': {'parts': [{'text': text}]},
                        'taskType': task_type,
                        'outputDimensionality': 768,
                    }
                    for text in texts
                ]
            },
        )
        if resp.status_code == 403:
            raise RuntimeError(
                'Gemini API key rejected (403). Check GOOGLE_API_KEY and that '
                'the Generative Language API is enabled in your Google Cloud project.'
            )
        resp.raise_for_status()
        return [item['values'] for item in resp.json()['embeddings']]
