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

_signup_counter = 0


def make_auth_headers(client, name="Test User", password="password123"):
    """Sign up a fresh user through the API and return auth headers.

    Each call uses a unique email so tests sharing one database never clash.
    """
    global _signup_counter
    _signup_counter += 1
    email = f"test{_signup_counter}@example.com"
    res = client.post(
        "/api/auth/signup",
        json={"name": name, "email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}
