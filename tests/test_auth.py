"""Auth tests: signup, login, token gating, and per-patient isolation."""
from fastapi.testclient import TestClient

from app.main import app
from conftest import make_auth_headers

client = TestClient(app)


def _signup(email, password="password123", name="Pat"):
    return client.post(
        "/api/auth/signup", json={"name": name, "email": email, "password": password}
    )


def test_signup_returns_token():
    res = _signup("signup1@example.com")
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "signup1@example.com"
    assert body["user"]["name"] == "Pat"


def test_signup_duplicate_email_rejected():
    assert _signup("dupe@example.com").status_code == 200
    assert _signup("dupe@example.com").status_code == 409


def test_signup_validates_input():
    assert _signup("bad-email", password="password123").status_code == 422
    assert _signup("short@example.com", password="123").status_code == 422


def test_login_roundtrip():
    assert _signup("login1@example.com", password="secret123").status_code == 200
    res = client.post(
        "/api/auth/login",
        json={"email": "login1@example.com", "password": "secret123"},
    )
    assert res.status_code == 200
    assert res.json()["access_token"]


def test_login_wrong_password_rejected():
    assert _signup("login2@example.com", password="secret123").status_code == 200
    res = client.post(
        "/api/auth/login",
        json={"email": "login2@example.com", "password": "wrongpass"},
    )
    assert res.status_code == 401


def test_login_unknown_email_rejected():
    res = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "whatever123"},
    )
    assert res.status_code == 401


def test_me_returns_current_user():
    headers = make_auth_headers(client)
    res = client.get("/api/auth/me", headers=headers)
    assert res.status_code == 200
    assert res.json()["email"].startswith("test")


def test_me_rejects_bad_token():
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer bogus"})
    assert res.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_patients_cannot_see_each_others_reports():
    from app.models.db import SessionLocal
    from app.models.entities import Report
    from app.services import auth_service

    def _uid(headers):
        return auth_service.decode_token(headers["Authorization"].split(" ", 1)[1])

    alice = make_auth_headers(client)
    bob = make_auth_headers(client)
    alice_id, bob_id = _uid(alice), _uid(bob)
    assert alice_id != bob_id

    db = SessionLocal()
    db.add(Report(user_id=alice_id, filename="alice.pdf", raw_text="x"))
    db.add(Report(user_id=bob_id, filename="bob.pdf", raw_text="y"))
    db.commit()
    alice_report = db.query(Report).filter(Report.filename == "alice.pdf").one()
    alice_report_id = alice_report.id
    db.close()

    # Bob sees only his own report, and Alice's id is invisible to him.
    bob_list = client.get("/api/reports", headers=bob).json()
    assert [r["filename"] for r in bob_list] == ["bob.pdf"]
    assert client.get(f"/api/reports/{alice_report_id}", headers=bob).status_code == 404
    assert (
        client.post(f"/api/reports/{alice_report_id}/analyze", headers=bob).status_code
        == 404
    )
    # Alice sees only hers.
    alice_list = client.get("/api/reports", headers=alice).json()
    assert [r["filename"] for r in alice_list] == ["alice.pdf"]
    assert (
        client.get(f"/api/reports/{alice_report_id}", headers=alice).status_code == 200
    )
