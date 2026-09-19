"""SQLAlchemy engine/session.

``DATABASE_URL`` selects the database: set it to a Postgres URL (e.g.
``postgresql://bloodiq:bloodiq@localhost:5432/bloodiq`` — see docker-compose.yml)
for the full setup, or leave it unset for the zero-setup SQLite fallback at
``data/bloodiq.db``.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.utils.paths import project_root

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    DB_PATH = project_root() / "data" / "bloodiq.db"
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{DB_PATH}"

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:  # Postgres via psycopg2
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
