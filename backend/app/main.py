from errno import EBADE
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app.routers import repos
from app.services import embedding as embedding_service

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info('Checking Ollama connection...')
    await embedding_service.initialize()
    logger.info('Ollama OK.')
    yield
    await engine.dispose()

app = FastAPI(title='Docs Q&A API', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://localhost:3000'], allow_methods=['*'], allow_headers=['*'])
app.include_router(repos.router)

@app.get('/health')
async def health():
    return {'status': 'ok'}