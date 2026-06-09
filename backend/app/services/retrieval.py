import logging
import httpx
from groq import AsyncGroq, APIStatusError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.models import Repo
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

def _normalize_answer(answer: str) -> str:
    cleaned = answer.strip().strip('"').strip("'")
    if cleaned == NOT_COVERED_MESSAGE or cleaned.lower().startswith(NOT_COVERED_MESSAGE.lower()):
        return NOT_COVERED_MESSAGE
    return answer.strip()

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
    answer = _normalize_answer(await _call_llm(question, context))

    if answer == NOT_COVERED_MESSAGE:
        return {'answer': NOT_COVERED_MESSAGE, 'sources': []}

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
            (1 - (embedding <=> CAST(:vec AS vector)))::float AS score
        FROM chunks
        WHERE repo_id = :repo_id
        ORDER BY embedding <=> CAST(:vec AS vector)
        LIMIT :top_k
    """)
    result = await db.execute(stmt, {'vec': vec_literal, 'repo_id': repo_id, 'top_k': top_k})

    return [dict(row) for row in result.mappings().all()]

async def _call_llm(question: str, context: str) -> str:
    settings = get_settings()
    messages = _chat_messages(question, context)

    if _groq_api_key_configured():
        try:
            logger.info(f'Calling Groq {settings.groq_llm_model}')
            return await _call_groq(messages, settings.groq_llm_model)
        except APIStatusError as e:
            logger.warning(f'Groq failed ({e.status_code}): {e.message}. Falling back to Ollama.')
        except Exception as e:
            logger.warning(f'Groq failed ({e}). Falling back to Ollama.')

    logger.info(f'Calling Ollama {settings.llm_model}')
    return await _call_ollama(messages, settings.llm_model)

async def _call_groq(messages: list[dict[str, str]], model: str) -> str:
    client = _get_groq_client()
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=1024,
        temperature=0.1,
    )

    return response.choices[0].message.content

async def _call_ollama(messages: list[dict[str, str]], model: str) -> str:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(
                f'{settings.ollama_url}/api/chat',
                json={'model': model, 'messages': messages, 'stream': False, 'options': {'temperature': 0.1}},
            )
            resp.raise_for_status()
        except httpx.ConnectError:
            raise RuntimeError(f'Cannot connect to Ollama at {settings.ollama_url}. Start it with: ollama serve')
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise RuntimeError(f"Model '{model}' not found in Ollama. Pull it first: ollama pull {model}")
            raise

        return resp.json()['message']['content']


