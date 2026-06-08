import logging
from groq import AsyncGroq
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.models import Repo
from app.services import embedding as embedding_service
from app.config import get_settings

logger = logging.getLogger(__name__)

_groq_client: AsyncGroq | None = None

def _get_groq_client() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        settings = get_settings()
        if not settings.groq_api_key:
            raise RuntimeError('GROQ_API_KEY is not set in .env. Get a free key at https://console.groq.com')
        _groq_client = AsyncGroq(api_key=settings.groq_api_key)
    return _groq_client

async def query_repo(question: str, repo_id: int, db: AsyncSession) -> dict:
    settings = get_settings()

    repo = await db.get(Repo, repo_id)
    if not repo:
        raise ValueError(f'No repo found with id={repo_id}')

    logger.info(f"Embedding query for repo '{repo.name}'")
    query_embedding = await embedding_service.encode_query(question)

    logger.info(f'Running vector search (top_k={settings.top_k})')
    chunks = await _vector_search(query_embedding, repo_id, settings.top_k, db)

    if not chunks:
        return {
            'answer': 'No relevant documentation found for this question.',
            'sources': []
        }

    context = '\n\n---\n\n'.join(f"[{i+1}] (file: {c['file_path']})\n{c['content']}" for i, c in enumerate(chunks))

    logger.info(f'Calling Groq {settings.llm_model}')
    answer = await _call_llm(question, context, settings.llm_model)

    return {
        'answer': answer,
        'sources': [
            {
                'index': i+1,
                'file_path': c['file_path'],
                'content': c['content'],
                'score': round(c['score'], 4)
            }
            for i, c in enumerate(chunks)
        ]
    }

async def _vector_search(query_embedding: list[float], repo_id: int, top_k: int, db: AsyncSession) -> list[dict]:
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

async def _call_llm(question: str, context: str, model: str) -> str:
    client = _get_groq_client()

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {
                'role': 'system',
                'content': (
                    'You are a documentation assistant. Answer questions using ONLY the provided context. '
                    'For every fact you state, cite its source number in square brackets, for example [1] or [2]. '
                    'If the answer is not present in the context, respond with exactly: '
                    '"This information is not covered in the documentation."'
                )
            },
            {
                'role': 'user',
                'content': f'Context:\n\n{context}\n\nQuestion: {question}'
            }
        ],
        max_tokens=1024,
        temperature=0.1,
    )

    return response.choices[0].message.content