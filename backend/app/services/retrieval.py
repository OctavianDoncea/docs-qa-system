import json
import logging
import httpx
from groq import AsyncGroq, APIStatusError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.services import embedding as embedding_service
from app.config import get_settings

logger = logging.getLogger(__name__)

_groq_client: AsyncGroq | None = None

NOT_COVERED_MESSAGE = 'This information is not covered in the documentation.'

SYSTEM_PROMPT = (
    'You are a documentation assistant. Answer questions using ONLY the provided context. '
    'For every fact you state, cite its source number in square brackets, for example [1] or [2]. '
    'If the answer is not present in the context, respond with exactly: '
    f'"{NOT_COVERED_MESSAGE}"'
)


def _get_groq_client() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        settings = get_settings()
        _groq_client = AsyncGroq(api_key=settings.groq_api_key)

    return _groq_client


def _chat_messages(question: str, context: str) -> list[dict[str, str]]:
    return [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': f'Context:\n\n{context}\n\nQuestion: {question}'},
    ]


def _groq_api_key_configured() -> bool:
    token = get_settings().groq_api_key.strip()
    return bool(token and token != 'your_groq_api_key')


def _sources_payload(chunks: list[dict]) -> list[dict]:
    return [
        {
            'index': i + 1,
            'file_path': c['file_path'],
            'content': c['content'],
            'score': round(c['score'], 4),
        }
        for i, c in enumerate(chunks)
    ]


async def stream_query_repo(question: str, repo_id: int, db: AsyncSession):
    """Full RAG pipeline as an async generator. Yields SSE-formatted strings consumed by the query StreamingResponse."""
    settings = get_settings()

    try:
        query_embedding = await embedding_service.encode_query(question)
        chunks = await _vector_search(query_embedding, repo_id, settings.top_k, db)

        if not chunks:
            yield 'data: ' + json.dumps({
                'content': 'No relevant documentation found for this question.',
                'done': True,
                'sources': [],
            }) + '\n\n'
            return

        context = '\n\n---\n\n'.join(
            f"[{i + 1}] (file: {c['file_path']})\n{c['content']}" for i, c in enumerate(chunks)
        )
        messages = _chat_messages(question, context)

        async for content in _stream_llm(messages):
            yield 'data: ' + json.dumps({'content': content, 'done': False}) + '\n\n'

        yield 'data: ' + json.dumps({
            'content': '',
            'done': True,
            'sources': _sources_payload(chunks),
        }) + '\n\n'

    except Exception as e:
        logger.exception('Streaming query failed')
        yield 'data: ' + json.dumps({'error': str(e), 'done': True}) + '\n\n'


async def _stream_llm(messages: list[dict[str, str]]):
    settings = get_settings()

    if _groq_api_key_configured():
        try:
            logger.info('Streaming Groq response (%s)', settings.groq_llm_model)
            async for content in _stream_groq(messages, settings.groq_llm_model):
                yield content
            return
        except APIStatusError as e:
            logger.warning('Groq failed (%s): %s. Falling back to Ollama.', e.status_code, e.message)
        except Exception as e:
            logger.warning('Groq failed (%s). Falling back to Ollama.', e)

    logger.info('Streaming Ollama response (%s)', settings.llm_model)
    async for content in _stream_ollama(messages, settings.llm_model):
        yield content


async def _stream_groq(messages: list[dict[str, str]], model: str):
    client = _get_groq_client()
    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=1024,
        temperature=0.1,
        stream=True,
    )

    async for chunk in stream:
        content = chunk.choices[0].delta.content
        if content is not None:
            yield content


async def _stream_ollama(messages: list[dict[str, str]], model: str):
    settings = get_settings()
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream(
                'POST',
                f'{settings.ollama_url}/api/chat',
                json={'model': model, 'messages': messages, 'stream': True, 'options': {'temperature': 0.1}},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    content = data.get('message', {}).get('content')
                    if content:
                        yield content
        except httpx.ConnectError:
            raise RuntimeError(
                f'Cannot connect to Ollama at {settings.ollama_url}. Start it with: ollama serve'
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise RuntimeError(
                    f"Model '{model}' not found in Ollama. Pull it first: ollama pull {model}"
                )
            raise


async def _vector_search(query_embedding: list[float], repo_id: int, top_k: int, db: AsyncSession) -> list[dict]:
    """Find the top_k most similar chunks using pgvector cosine distance."""
    vec_literal = '[' + ','.join(str(float(x)) for x in query_embedding) + ']'
    stmt = text("""
        SELECT
            file_path,
            content,
            (1 - (embedding <=> :vec::vector))::float AS score
        FROM chunks
        WHERE repo_id = :repo_id
        ORDER BY embedding <=> :vec::vector
        LIMIT :top_k
    """)

    result = await db.execute(stmt, {'vec': vec_literal, 'repo_id': repo_id, 'top_k': top_k})

    return [dict(row) for row in result.mappings().all()]
