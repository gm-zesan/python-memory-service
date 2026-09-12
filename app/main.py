import logging
from contextlib import asynccontextmanager
# pyrefly: ignore [missing-import]
from fastapi import FastAPI
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
from .config import config
from .api import router as memory_router
from .analytics.router import router as analytics_router
from .neo4j_client import neo4j_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("python_memory_service")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {config.SERVICE_NAME} v{config.VERSION} on port {config.PORT}...")
    # Initialize Neo4j driver connection
    neo4j_client.get_driver()
    health = neo4j_client.health_check()
    logger.info(f"Neo4j Status: {health.get('status')}")
    yield
    logger.info(f"Shutting down {config.SERVICE_NAME}...")
    neo4j_client.close()

app = FastAPI(
    title="Conversation Graph Memory Service",
    version=config.VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(memory_router)
app.include_router(analytics_router)

if __name__ == "__main__":
    # pyrefly: ignore [missing-import]
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
