import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.database import engine, Base
from api.models import *  # noqa: F401 — register all models

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("VaultMaster API started")
    yield
    # Shutdown
    await engine.dispose()
    logger.info("VaultMaster API stopped")


app = FastAPI(
    title="VaultMaster",
    description="Backup Control Center — REST API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from api.routers import auth, servers, jobs, runs, artifacts, storage, retention, notifications, dashboard

app.include_router(auth.router, prefix="/api/v1")
app.include_router(servers.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(runs.router, prefix="/api/v1")
app.include_router(artifacts.router, prefix="/api/v1")
app.include_router(storage.router, prefix="/api/v1")
app.include_router(retention.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "vaultmaster"}
