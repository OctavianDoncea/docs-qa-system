import logging
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.models import Chunk, Repo
from app.services import embedding as embedding_service
from app.services.github import fetch_repo_docs, parse_github_url
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

async def ingest_repo(url: str, db: AsyncSession, reingest: bool = False) -> Repo:
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

    # 1. fetch
    logger.info(f'Fetching docs from {url}')
    files = await fetch_repo_docs(url)

    if not files:
        raise ValueError(f'No documentation files found in {url}. The repo may be private or have no .md/.rst/.txt files.')

    logger.info(f'Fetched {len(files)} files')

    # 2. split
    logger.info(f'Splitting into chunks (max_chars={settings.chunk_size}, overlap={settings.chunk_overlap})')
    all_chunks: list[dict] = []

    for file in files:
        chunks = split_markdown(file['content'], max_chars=settings.chunk_size, overlap=settings.chunk_overlap)
        for i, text in enumerate(chunks):
            all_chunks.append({'file_path': file['path'], 'content': text, 'chunk_index': i})

    if not all_chunks:
        raise ValueError('Files were not found but contained no extractable content.')

    logger.info(f'Created {len(all_chunks)} chunks across {len(files)} files')

    # 3. embed via Ollama
    logger.info(f'Embedding {len(all_chunks)} chunks via Ollama...')
    texts = [c['content'] for c in all_chunks]
    embeddings = await embedding_service.encode_documents(texts)

    # 4. bulk insert
    logger.info('Saving to database')
    db.add_all([
        Chunk(
            repo_id=repo.id,
            file_path=c['file_path'],
            content=c['content'],
            embedding=embeddings[i],
            chunk_index=c['chunk_index']
        )
        for i, c in enumerate(all_chunks)
    ])
    repo.chunk_count = len(all_chunks)

    await db.commit()
    await db.refresh(repo)

    logger.info(f'Done. {repo.chunk_count} chunks ingested for {name}')
    return repo

def split_markdown(text: str, max_chars: int = 1500, overlap: int = 200) -> list[str]:
    heading_re = re.compile(r"(?=^#{1,3} )", re.MULTILINE)
    sections = [s.strip() for s in heading_re.split(text) if s.strip()]

    chunks: list[str] = []
    for section in sections:
        if len(section) <= max_chars:
            chunks.append(section)
        else:
            chunks.extend(_split_by_paragraph(section, max_chars, overlap))
    return [c for c in chunks if len(c) >= 100 ]

def _split_by_paragraph(text: str, max_chars: int, overlap: int) -> list[str]:
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
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result: list[str] = []
    current = ''

    for s in sentences:
        candidate = f'{current} {s}'.strip() if current else s
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                result.append(current)
            tail = current[-overlap:] if len(current) > overlap else current
            current = f'{tail} {s}'.strip() if tail else s

    if current:
        result.append(current)
    
    return result