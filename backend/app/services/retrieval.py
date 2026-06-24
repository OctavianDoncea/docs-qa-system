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

MAX_HISTORY_TURNS = 3
MAX_HISTORY_CHARS = 800
RERANK_SNIPPET_CHARS = 400

NOT_COVERED_MESSAGE = 'This information is not covered in the documentation.'


def _get_groq_client() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        settings = get_settings()
        if not settings.groq_api_key:
            raise  RuntimeError('GROQ_API_KEY is not set in .env. Get a free key at https://console.groq.com')
        _groq_client = AsyncGroq(api_key=settings.groq_api_key)

    return _groq_client

def _prepare_history(history: list[dict]) -> list[dict]:
    cleaned = [
        {'role': h['role'], 'content': h['content'][:MAX_HISTORY_CHARS]}
        for h in history
        if h.get('role') in ('user', 'assistant') and h.get('content')
    ]

    return cleaned[-(MAX_HISTORY_TURNS * 2):]

async def _condense_question(question: str, history: list[dict], model: str) -> str:
    if not history or not _groq_api_key_configured():
        return question

    client = _get_groq_client()
    convo = '\n'.join(f"{h['role'].capitalize()}: {h['content']}" for h in history)

    prompt = (
        f'Conversation so far:\n{convo}\n\n'
        f'Follow-up question: {question}\n\n'
        'Rewrite the follow-up question as a standalone question that '
        'includes all context needed to understand it without the '
        'conversation above. Preserve technical terms, function names, '
        'and identifiers exactly as written. If the follow-up question '
        'is already standalone, return it unchanged. '
        'Output only the rewritten question — no explanation, no quotes.'
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=120,
            temperature=0,
        )
        condensed = response.choices[0].message.content.strip()
        return condensed or question
    except Exception as e:
        logger.warning('Question condensing failed, using original question: %s', e)
        return question

async def _rerank(question: str, chunks: list[dict], top_k: int, model: str) -> list[dict]:
    """Use the LLM to score each candidate chunk's relevance to the question, then return the top k by that score"""
    if len(chunks) <= top_k:
        return chunks

    client = _get_groq_client()

    passages = '\n\n'.join(f"[{i}] {c['content'][:RERANK_SNIPPET_CHARS]}" for i, c in enumerate(chunks))
    prompt = (f'Question: {question}\n\nPassages:\n{passages}\n\n'
        'Score how well each passage answers the question, from 0 (irrelevant) to 10 (directly answers it).'
        'Respond with only a JSON object mapping each passage index (as a string) to its integer score, e.g. {"0": 8, "1": 2, "2": 5}.'
        'No explanation, no markdown, no code fences.'
    )

    try:
        response = await client.chat.completions.create(
            model = model,
            messages = [{'role': 'user', 'content': prompt}],
            max_tokens = 300,
            temperature = 0,
            response_format = {'type': 'json_object'}
        )
        raw = response.choices[0].message.content
        scores = json.loads(raw)

        scored = [(chunks[i], int(scores.get(str(i), 0))) for i in range(len(chunks))]
        scored.sort(key=lambda pair: pair[1], reverse=True)

        reranked = [chunk for chunk, _ in scored[:top_k]]
        logger.info(f'Re-ranked {len(chunks)} candidates -> top {top_k} (LLM scores: {[s for _, s in scored[:top_k]]})')

        return reranked
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
        logger.warning(f'Re-ranking failed, using hybrid order: {e}')
        return chunks[:top_k]

def _build_messages_with_history(question: str, context: str, history: list[dict]) -> list[dict[str, str]]:
    system_prompt = (
        'You are a documentation assistant having an ongoing conversation with a user. '
        'Use the conversation history ONLY to understand what the user is referring to '
        '(e.g. resolving "it", "that", or implicit subjects from earlier turns). '
        'Base every factual claim strictly on the Context section provided in the final message, '
        'never on prior assistant answers, which may be incomplete. '
        'For every fact you state, cite its source number in square brackets, for example [1] or [2]. '
        f'If the answer is not present in the context, respond with exactly: "{NOT_COVERED_MESSAGE}"'
    )

    messages: list[dict[str, str]] = [{'role': 'system', 'content': system_prompt}]
    for h in history:
        messages.append({'role': h['role'], 'content': h['content']})
    messages.append({
        'role': 'user',
        'content': f'Context:\n\n{context}\n\nQuestion: {question}',
    })
    return messages


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


async def stream_query_repo(question: str, repo_id: int, db: AsyncSession, history: list[dict] | None = None):
    """
    Full RAG pipeline: condense -> hybrid search -> confidence gate ->
    stream the answer (or decline). Yields SSE-formatted strings.
    """
    settings = get_settings()
    history = _prepare_history(history or [])

    try:
        search_question = await _condense_question(question, history, settings.llm_model)
        was_rewritten = search_question.strip().lower() != question.strip().lower()
        if was_rewritten:
            logger.info(f'Condensed question: {question} -> {search_question}')
        
        query_embedding = await embedding_service.encode_query(search_question)
        retrieve_n = settings.rerank_candidates if settings.rerank_enabled else settings.top_k
        chunks = await _hybrid_search(query_embedding, search_question, repo_id, retrieve_n, db)

        if not chunks:
            yield 'data: ' + json.dumps({
                'content': 'No relevant documentation found for this question.',
                'done': False,
            }) + '\n\n'
            yield 'data: ' + json.dumps({
                'content': '',
                'done': True,
                'sources': [],
            }) + '\n\n'
            return

        if settings.rerank_enabled:
            chunks = await _rerank(question, chunks, settings.top_k, settings.groq_llm_model)
        else:
            chunks = chunks[:settings.top_k]
        
        max_score = max(c['score'] for c in chunks)
        if max_score < settings.confidence_threshold:
            pct = round(max_score * 100)
            threshold_pct = round(settings.confidence_threshold * 100)
            logger.info(
                'Low confidence (%.3f < %.3f) - skipping LLM call',
                max_score,
                settings.confidence_threshold,
            )
            message = (
                f"This query doesn't appear to be covered in the loaded documentation. "
                f'Best match: {pct}% similarity (threshold: {threshold_pct}%). '
                'Try rephrasing or loading a different repository.'
            )
            yield 'data: ' + json.dumps({'content': message, 'done': False}) + '\n\n'
            yield 'data: ' + json.dumps({
                'content': '',
                'done': True,
                'sources': [],
                'low_confidence': True,
                'confidence': round(max_score, 4),
            }) + '\n\n'
            return

        context = '\n\n---\n\n'.join(
            f"[{i + 1}] (file: {c['file_path']})\n{c['content']}" for i, c in enumerate(chunks)
        )
        messages = _build_messages_with_history(question, context, history)

        async for content in _stream_llm(messages):
            yield 'data: ' + json.dumps({'content': content, 'done': False}) + '\n\n'

        done_payload: dict = {
            'content': '',
            'done': True,
            'sources': _sources_payload(chunks),
        }
        if was_rewritten:
            done_payload['search_query'] = search_question

        yield 'data: ' + json.dumps(done_payload) + '\n\n'

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


async def _hybrid_search(query_embedding: list[float], question: str, repo_id: int, top_k: int, db: AsyncSession) -> list[dict]:
    """
    Hybrid retrieval: pgvector cosine search + PostgreSQL full-text search,
    fused with Reciprocal Rank Fusion (RRF).
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
            (1 - (c.embedding <=> :vec::vector))::float AS score
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
