import asyncio
import logging
import random
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

_EMBED_MODEL = 'gemini-embedding-001'
_EMBED_URL = (
    'https://generativelanguage.googleapis.com'
    f'/v1beta/models/{_EMBED_MODEL}:embedContent'
)

_REQUEST_SPACING = 0.5   # seconds between successive embed calls
_MAX_RETRIES = 6
_MAX_BACKOFF = 30.0      # cap for exponential backoff, seconds


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
    settings = get_settings()
    headers = {'x-goog-api-key': settings.google_api_key}
    embeddings: list[list[float]] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for i, text in enumerate(texts):
            if i:
                await asyncio.sleep(_REQUEST_SPACING)
            embeddings.append(await _embed_one(client, headers, text, task_type))
    return embeddings


def _retry_delay(resp: httpx.Response) -> float | None:
    """Extract Google's suggested retry delay from a 429/5xx response, if any."""
    retry_after = resp.headers.get('retry-after')
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    try:
        for detail in resp.json().get('error', {}).get('details', []):
            delay = detail.get('retryDelay')  # google.rpc.RetryInfo, e.g. "17s"
            if isinstance(delay, str) and delay.endswith('s'):
                return float(delay[:-1])
    except Exception:
        pass
    return None


async def _embed_one(client: httpx.AsyncClient, headers: dict, text: str, task_type: str) -> list[float]:
    payload = {
        'model': f'models/{_EMBED_MODEL}',
        'content': {'parts': [{'text': text}]},
        'taskType': task_type,
        'outputDimensionality': 768,
    }
    for attempt in range(_MAX_RETRIES):
        resp = await client.post(_EMBED_URL, headers=headers, json=payload)

        if resp.status_code == 403:
            raise RuntimeError(
                'Gemini API key rejected (403). Check GOOGLE_API_KEY and that '
                'the Generative Language API is enabled in your Google Cloud project.'
            )

        if resp.status_code in (429, 500, 503) and attempt < _MAX_RETRIES - 1:
            delay = _retry_delay(resp)
            if delay is None:
                delay = min(2 ** attempt, _MAX_BACKOFF) + random.uniform(0, 1)
            logger.warning(
                'Gemini embed rate-limited/unavailable (%s); retrying in %.1fs (attempt %d/%d)',
                resp.status_code, delay, attempt + 1, _MAX_RETRIES,
            )
            await asyncio.sleep(delay)
            continue

        resp.raise_for_status()
        return resp.json()['embedding']['values']

    raise RuntimeError('Gemini embedding failed after exhausting retries (rate limited).')
