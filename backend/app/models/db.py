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


def ensure_columns() -> None:
    """Lightweight migration for columns added after a DB was created.

    ``create_all`` never alters existing tables, so a column added to a
    model (e.g. ``results.flag``) would otherwise be missing on databases
    created by an older build. Runs at startup; safe to call repeatedly.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "results" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("results")}
    if "flag" not in existing:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE results ADD COLUMN flag VARCHAR(12)"))
    if "reports" in inspector.get_table_names():
        existing_reports = {
            col["name"] for col in inspector.get_columns("reports")
        }
        if "extraction_source" not in existing_reports:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE reports ADD COLUMN extraction_source VARCHAR(8)")
                )
        if "user_id" not in existing_reports:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE reports ADD COLUMN user_id INTEGER"))
        if "source_type" not in existing_reports:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE reports ADD COLUMN source_type VARCHAR(16)"))


def get_db():
    """FastAPI dependency: yields a session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
