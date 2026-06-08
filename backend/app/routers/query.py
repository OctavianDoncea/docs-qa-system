import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.database import get_db
from app.services import retrieval

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/query', tags=['query'])

class QueryRequest(BaseModel):
    question: str
    repo_id: int


class SourceResponse(BaseModel):
    index: int
    file_path: str
    content: str
    score: float


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]


@router.post('', response_model=QueryResponse)
async def query(request: QueryRequest, db: AsyncSession = Depends(get_db)):
    try:
        result = await retrieval.query_repo(question=request.question, repo_id = request.repo_id, db=db)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception('Query failed unexpectedly')
        raise HTTPException(status_code=500, detail=f'Query failed: {e}')