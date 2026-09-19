"""Test setup: put backend/ on sys.path and use an isolated temp SQLite DB.

DATABASE_URL must be set before app modules are imported (the engine is
created at import time), so this lives in conftest.py, which pytest imports
before any test module.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

_tmp = tempfile.mkdtemp(prefix="bloodiq_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
