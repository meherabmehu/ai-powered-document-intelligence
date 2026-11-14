from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api import router
from app.config import get_settings
from app.database import create_database_schema


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_database_schema()
    yield

app = FastAPI(
    title="AI-Powered Document Intelligence",
    version="0.1.0",
    description="Upload, process, validate, and search business documents.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


# In the Render container, serve the compiled React app from the same origin as
# the API so browser requests stay same-origin and uploads share the worker's disk.
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
