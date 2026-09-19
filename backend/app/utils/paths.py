"""Project-root resolution helper.

The project root is defined as the parent of the ``backend/`` directory, so
paths (SQLite file, uploads, frontend) resolve identically whether the server
is started from inside ``backend/`` (``uvicorn app.main:app``) or from the
project root (``PYTHONPATH=backend uvicorn app.main:app``).
"""
from pathlib import Path


def project_root() -> Path:
    """Return the project root (parent of the ``backend/`` directory)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "backend":
            return parent.parent
    raise RuntimeError("Could not locate the backend/ directory from " + str(here))
