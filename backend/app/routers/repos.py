import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.database import get_db
from app.models import Chunk, Repo
from app.services import ingestion

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/repos', tags=['repos'])

class IngestRequest(BaseModel):
    url: str
    reingest: bool = False


class RepoResponse(BaseModel):
    id: int
    url: str
    name: str
    chunk_count: int

    model_config = {'from_attributes': True}


@router.post('', response_model=RepoResponse, status_code=status.HTTP_201_CREATED)
async def ingest_repo(request: IngestRequest, db: AsyncSession = Depends(get_db)):
    try:
        repo = await ingestion.ingest_repo(url=request.url, db=db, reingest=request.reingest)
        return repo
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception('Ingestion failed unexpectedly')
        raise HTTPException(status_code=500, detail=f'Ingestion failed: {e}')

@router.get('', response_model=list[RepoResponse])
async def list_repos(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Repo).order_by(Repo.ingested_at.desc()))
    return result.scalars().all()

@router.delete('/{repo_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_repo(repo_id: int, db: AsyncSession = Depends(get_db)):
    repo = await db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail='Repo not found')
    await db.delete(repo)
    await db.commit()