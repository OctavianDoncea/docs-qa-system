import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import Repo
from app.services import retrieval

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/query', tags=['query'])

class HistoryMessage(BaseModel):
    role: str
    content: str


class QueryRequest(BaseModel):
    question: str
    repo_id: int
    history: list[HistoryMessage] = []


@router.post('', summary='Ask a question about an ingested repository', response_description='text/event-stream of SSE events. Each event: {content, done} or {content, done, sources} or {error, done}.')
async def query(request: QueryRequest, db: AsyncSession = Depends(get_db)):
    """Streams the answer as Server-Sent Events."""

    repo = await db.get(Repo, request.repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f'No repo found with id {request.repo_id}.')

    history_dicts = [h.model_dump() for h in request.history]

    async def generate():
        async for chunk in retrieval.stream_query_repo(question=request.question, repo_id=request.repo_id, db=db, history=history_dicts):
            yield chunk

    return StreamingResponse(generate(), media_type='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
        'Connection': 'keep-alive',
    })