"""BloodIQ FastAPI application.

API routes live under /api. The static frontend (frontend/) is served at /.

Run from inside backend/:
    uvicorn app.main:app --reload

Run from the project root:
    PYTHONPATH=backend uvicorn app.main:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import biomarkers, chat, reports
from app.models.db import engine, ensure_columns
from app.models.entities import Base  # noqa: F401  (registers the tables)
from app.utils.paths import project_root

# Create tables on startup (no migrations needed for this scope).
Base.metadata.create_all(bind=engine)
# Backfill columns added after older databases were created.
ensure_columns()

app = FastAPI(title="BloodIQ", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reports.router, prefix="/api/reports")
app.include_router(biomarkers.router, prefix="/api/biomarkers")
app.include_router(chat.router, prefix="/api/chat")


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the no-build-step frontend last, so /api routes take precedence.
FRONTEND_DIR = project_root() / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
