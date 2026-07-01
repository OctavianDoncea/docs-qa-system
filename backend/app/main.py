import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app.routers import repos, query
from app.services import embedding as embedding_service
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-8s  %(name)s  %(message)s')
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info('Checking Gemini embedding API...')
    await embedding_service.initialize()
    logger.info('Gemini OK.')
    yield
    await engine.dispose()


settings = get_settings()

app = FastAPI(title='Docs Q&A API', version='0.1.0', lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.allowed_origins.split(',') if o.strip()],
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(repos.router)
app.include_router(query.router)


@app.get('/health')
async def health():
    return {'status': 'ok'}
