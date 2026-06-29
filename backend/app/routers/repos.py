import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.database import get_db
from app.models import IngestJob, Repo
from app.services import ingestion

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/repos', tags=['repos'])

class IngestRequest(BaseModel):
    url: str
    reingest: bool = False


class JobResponse(BaseModel):
    job_id: int
    status: str

    model_config = {'from_attributes': True}


class JobStatusResponse(BaseModel):
    job_id: int
    status: str
    phase: str | None
    progress: int
    repo_id: int | None
    error: str | None

    model_config = {'from_attributes': True}


class RepoResponse(BaseModel):
    id: int
    url: str
    name: str
    chunk_count: int

    model_config = {'from_attributes': True}


@router.post('', response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_repo(request: IngestRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    job = IngestJob(repo_url=request.url, status='pending', progress=0)
    db.add(job)
    await db.commit()
    await db.refresh(job)

    background_tasks.add_task(ingestion.run_ingest_job, job.id, request.url, request.reingest)

    return JobResponse(job_id=job.id, status=job.status)

@router.get('/job/{job_id}', response_model=JobStatusResponse)
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(IngestJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    return JobStatusResponse(job_id=job.id, status=job.status, phase=job.phase, progress=job.progress, repo_id=job.repo_id, error=job.error)

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