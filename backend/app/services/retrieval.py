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
            'score': round(float(c['score']), 4),
        }
        for i, c in enumerate(chunks)
    ]


async def stream_query_repo(question: str, repo_id: int, db: AsyncSession):
    """
    Full RAG pipeline with hybrid retrieval, as an async generator.
    Yields SSE-formatted strings consumed by the /query StreamingResponse.

    Steps:
    1. Embed the question via Ollama (encode_query)
    2. Hybrid search: vector + keyword, fused with RRF
    3. Build a prompt with inline source references
    4. Stream the LLM response token by token (Groq, with Ollama fallback)
    5. Yield a final event with the source list
    """
    settings = get_settings()

    try:
        query_embedding = await embedding_service.encode_query(question)
        chunks = await _hybrid_search(
            query_embedding, question, repo_id, settings.top_k, db
        )

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


async def _hybrid_search(
    query_embedding: list[float],
    question: str,
    repo_id: int,
    top_k: int,
    db: AsyncSession,
) -> list[dict]:
    """
    Hybrid retrieval: pgvector cosine search + PostgreSQL full-text search,
    fused with Reciprocal Rank Fusion (RRF).

    score(d) = 1/(k + rank_vector(d)) + 1/(k + rank_keyword(d))   k = 60

    Each branch retrieves candidate_limit results independently. A FULL OUTER
    JOIN ensures chunks found by only one branch are still included (scoring
    0 from the missing branch). Falls back to pure vector search automatically
    when the keyword branch is empty (stop-word-only queries, no term matches).
    """
    vec_literal = '[' + ','.join(str(float(x)) for x in query_embedding) + ']'

    # Wider candidate pool gives RRF more material to rerank.
    # top_k=5 -> candidate_limit=20; top_k=10 -> candidate_limit=40 (capped at 50)
    candidate_limit = min(max(top_k * 4, 20), 50)

    stmt = text("""
        WITH
            vector_search AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (ORDER BY embedding <=> :vec::vector) AS rank
                FROM chunks
                WHERE repo_id = :repo_id
                ORDER BY embedding <=> :vec::vector
                LIMIT :candidate_limit
            ),

            keyword_search AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        ORDER BY ts_rank_cd(content_tsv, websearch_to_tsquery('english', :question)) DESC
                    ) AS rank
                FROM chunks
                WHERE repo_id = :repo_id
                  AND content_tsv @@ websearch_to_tsquery('english', :question)
                ORDER BY ts_rank_cd(content_tsv, websearch_to_tsquery('english', :question)) DESC
                LIMIT :candidate_limit
            ),

            rrf AS (
                SELECT
                    COALESCE(v.id, k.id) AS id,
                    COALESCE(1.0 / (60 + v.rank), 0.0)
                    + COALESCE(1.0 / (60 + k.rank), 0.0) AS rrf_score
                FROM vector_search v
                FULL OUTER JOIN keyword_search k ON v.id = k.id
            )

        SELECT
            c.file_path,
            c.content,
            r.rrf_score AS score
        FROM rrf r
        JOIN chunks c ON c.id = r.id
        ORDER BY r.rrf_score DESC
        LIMIT :top_k
    """)

    result = await db.execute(
        stmt,
        {
            'vec': vec_literal,
            'question': question,
            'repo_id': repo_id,
            'candidate_limit': candidate_limit,
            'top_k': top_k,
        },
    )

    return [dict(row) for row in result.mappings().all()]
