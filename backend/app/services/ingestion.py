import ast
import logging
import re
from typing import Awaitable, Callable
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.models import Chunk, Repo, IngestJob
from app.database import AsyncSessionLocal
from app.services import embedding as embedding_service
from app.services.github import fetch_repo_docs, parse_github_url
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

ProgressFn = Callable[[str, int], Awaitable[None]]

async def _noop_progress(phase: str, percent: int) -> None:
    """Default progress callback that does nothing, used by direct calls."""
    return None

async def ingest_repo(url: str, db: AsyncSession, reingest: bool = False, progress: ProgressFn = _noop_progress) -> Repo:
    owner, repo = parse_github_url(url)
    name = f'{owner}/{repo}'
    url = f'https://github.com/{owner}/{repo}'

    existing = await db.scalar(select(Repo).where(Repo.url == url))
    if existing and not reingest:
        raise ValueError(f"'{name}' is already ingested (id={existing.id}). Pass reingest=true to re-index it.")

    if existing and reingest:
        logger.info(f'Re-ingesting {name}: removing {existing.chunk_count} old chunks')
        await db.execute(delete(Chunk).where(Chunk.repo_id == existing.id))
        repo = existing
        repo.chunk_count = 0
    else:
        repo = Repo(url=url, name=name)
        db.add(repo)
        await db.flush()

    await progress('fetching', 10)
    files = await fetch_repo_docs(url)
    if not files:
        raise ValueError(f'No documentation files found in {url}. The repo may be private or have no .md/.rst/.txt/.py files.')

    await progress('chunking', 30)
    all_chunks: list[dict] = []
    for file in files:
        path = file['path']
        if path.lower().endswith('.py'):
            texts = extract_python_docstrings(file['content'])
        else:
            texts = split_markdown(file['content'], max_chars=settings.chunk_size, overlap=settings.chunk_overlap)
        for i, text in enumerate(texts):
            all_chunks.append({'file_path': path, 'content': text, 'chunk_index': i})

    if not all_chunks:
        raise ValueError('Files were found but contained no extractable content.')

    await progress('embedding', 40)
    texts = [c['content'] for c in all_chunks]
    batch_size = 64
    embeddings: list[list[float]] = []
    total = len(texts)

    for start in range(0, total, batch_size):
        batch = texts[start : start + batch_size]
        embeddings.extend(await embedding_service.encode_documents(batch))
        done = min(start + batch_size, total)
        pct = 40 + int(50 * done / total)
        await progress('embedding', pct)

    await progress('saving', 95)
    db.add_all([
        Chunk(
            repo_id = repo.id,
            file_path = c['file_path'],
            content = c['content'],
            embedding = embeddings[i],
            chunk_index = c['chunk_index'],
        )
        for i, c in enumerate(all_chunks)
    ])
    repo.chunk_count = len(all_chunks)

    await db.commit()
    await db.refresh(repo)
    await progress('done', 100)

    logger.info(f'Done. {repo.chunk_count} chunks ingested for {name}')
    return repo

async def run_ingest_job(job_id: int, url: str, reingest: bool) -> None:
    """Background entry point, owns its own DB session, updates the IngestJob rows as it progresses."""
    async with AsyncSessionLocal() as db:
        job = await db.get(IngestJob, job_id)
        if job is None:
            logger.error(f'Ingest job {job_id} not found')
            return

        async def report(phase: str, percent: int) -> None:
            job.status = 'running'
            job.phase = phase
            job.progress = percent
            await db.commit()

        try:
            repo = await ingest_repo(url, db, reingest=reingest, progress=report)
            job.status = 'completed'
            job.phase = 'done'
            job.progress = 100
            job.repo_id = repo.id
            await db.commit()
        except Exception as e:
            logger.exception(f'Ingest job {job_id} failed')
            await db.rollback()
            job = await db.get(IngestJob, job_id)
            if job:
                job.status = 'failed'
                job.error = str(e)
                await db.commit()

def extract_python_docstrings(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as e:
        logger.warning(f'Skipping unparseable Python file: {e}')
        return []

    chunks: list[str] = []
    module_doc = ast.get_docstring(tree)
    if module_doc and len(module_doc.strip()) >= 40:
        chunks.append(module_doc.strip())

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node)
            if not doc or len(doc.strip()) < 40:
                continue
            chunks.append(f"{_node_label(node)}\n\n{doc.strip()}")

    return chunks

def _node_label(node) -> str:
    if isinstance(node, ast.ClassDef):
        return f'class {node.name}'
    args = [a.arg for a in node.args.args]
    prefix = 'async def' if isinstance(node, ast.AsyncFunctionDef) else 'def'
    return f'{prefix} {node.name}({", ".join(args)})'

def split_markdown(text: str, max_chars: int = 1500, overlap: int = 200) -> list[str]:
    heading_re = re.compile(r'(?=^#{1,3} )', re.MULTILINE)
    sections = [s.strip() for s in heading_re.split(text) if s.strip()]
    chunks: list[str] = []
    for section in sections:
        if len(section) <= max_chars:
            chunks.append(section)
        else:
            chunks.extend(_split_by_paragraphs(section, max_chars, overlap))
    return [c for c in chunks if len(c) >= 100]

def _split_by_paragraphs(text: str, max_chars: int, overlap: int) -> list[str]:
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    result: list[str] = []
    current = ''
    for p in paragraphs:
        candidate = f'{current}\n\n{p}'.strip() if current else p
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                result.append(current)
            if len(p) > max_chars:
                result.extend(_split_by_sentences(p, max_chars, overlap))
                current = ''
            else:
                current = p
    if current:
        result.append(current)
    return result

def _split_by_sentences(text: str, max_chars: int, overlap: int) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    result: list[str] = []
    current = ''
    for sentence in sentences:
        candidate = f'{current} {sentence}'.strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                result.append(current)
            tail = current[-overlap:] if len(current) > overlap else current
            current = f'{tail} {sentence}'.strip() if tail else sentence
    if current:
        result.append(current)
    return result