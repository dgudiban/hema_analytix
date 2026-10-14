"""Family profile tests: CRUD, report scoping, and cross-account isolation."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from conftest import make_auth_headers

client = TestClient(app)


@pytest.fixture()
def user_a():
    return make_auth_headers(client)


@pytest.fixture()
def user_b():
    return make_auth_headers(client)


def _create_member(headers, **kw):
    body = {"name": "Amma", "relationship": "mother", "sex": "female"}
    body.update(kw)
    r = client.post("/api/family", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_crud_member(user_a):
    m = _create_member(user_a, date_of_birth="1965-04-02")
    assert m["name"] == "Amma" and m["relationship"] == "mother"
    assert m["sex"] == "female" and m["report_count"] == 0

    r = client.get("/api/family", headers=user_a)
    assert r.status_code == 200 and len(r.json()) == 1

    r = client.put(f"/api/family/{m['id']}", json={"name": "Mother"}, headers=user_a)
    assert r.status_code == 200 and r.json()["name"] == "Mother"

    r = client.delete(f"/api/family/{m['id']}", headers=user_a)
    assert r.status_code == 200

    r = client.get("/api/family", headers=user_a)
    assert r.json() == []


def test_member_validation(user_a):
    r = client.post("/api/family", json={"name": "  "}, headers=user_a)
    assert r.status_code == 400
    r = client.post(
        "/api/family", json={"name": "X", "relationship": "cousin"}, headers=user_a
    )
    assert r.status_code == 400
    r = client.post("/api/family", json={"name": "X", "sex": "unknown"}, headers=user_a)
    assert r.status_code == 400


def test_members_invisible_across_accounts(user_a, user_b):
    m = _create_member(user_a)
    # B cannot see, edit, or delete A's member.
    assert client.get("/api/family", headers=user_b).json() == []
    assert client.get(f"/api/family/{m['id']}", headers=user_b).status_code in (404, 405)
    r = client.put(f"/api/family/{m['id']}", json={"name": "Hax"}, headers=user_b)
    assert r.status_code == 404
    r = client.delete(f"/api/family/{m['id']}", headers=user_b)
    assert r.status_code == 404
    # And cannot file reports under it.
    r = client.get("/api/reports", params={"member_id": m["id"]}, headers=user_b)
    assert r.status_code == 404


def test_reports_scoped_by_member(user_a):
    m = _create_member(user_a)
    # Fake two reports directly via upload-less path is heavy; instead verify
    # list scoping: empty member list vs owner list both work and are separate.
    own = client.get("/api/reports", headers=user_a)
    assert own.status_code == 200
    mem = client.get("/api/reports", params={"member_id": m["id"]}, headers=user_a)
    assert mem.status_code == 200 and mem.json() == []
    # Unknown member id -> 404.
    r = client.get("/api/reports", params={"member_id": 999999}, headers=user_a)
    assert r.status_code == 404
    # Trends for the member with no data -> 404, not a leak of owner data.
    r = client.get("/api/reports/trends/BM001", params={"member_id": m["id"]}, headers=user_a)
    assert r.status_code == 404


def _upload_analyze_member(headers, member_id, monkeypatch, tmp_path, lines=None):
    """Upload + rule-parse a tiny PDF under a family profile."""
    import sys
    sys.path.insert(0, "tests")
    from test_api import make_pdf
    from app.services import pdf_service

    monkeypatch.setattr(pdf_service, "UPLOAD_DIR", tmp_path)
    monkeypatch.setenv("AI_EXTRACTION", "off")
    lines = lines or [
        "Report Date: 02/10/2026",
        "Hemoglobin 11.2 g/dL (12.0-15.5)",
        "WBC: 6,500 /uL  Ref 4,000-11,000",
    ]
    data = {}
    if member_id is not None:
        data["member_id"] = str(member_id)
    up = client.post(
        "/api/reports/upload",
        files={"file": ("r.pdf", make_pdf(lines), "application/pdf")},
        data=data,
        headers=headers,
    )
    assert up.status_code == 200, up.text
    rid = up.json()["report_id"]
    an = client.post(f"/api/reports/{rid}/analyze", headers=headers)
    assert an.status_code == 200, an.text
    return rid, an.json()


def test_member_report_lifecycle(user_a, monkeypatch, tmp_path):
    m = _create_member(user_a)
    rid, analyzed = _upload_analyze_member(user_a, m["id"], monkeypatch, tmp_path)
    assert any(r["standard_name"] == "Hemoglobin" for r in analyzed["results"])

    # Owner list stays empty; member list has the report.
    assert client.get("/api/reports", headers=user_a).json() == []
    mem_reports = client.get(
        "/api/reports", params={"member_id": m["id"]}, headers=user_a
    ).json()
    assert [r["id"] for r in mem_reports] == [rid]

    # Trends scoped: member has points, owner has none.
    t = client.get(
        "/api/reports/trends/BM001", params={"member_id": m["id"]}, headers=user_a
    )
    assert t.status_code == 200 and len(t.json()["points"]) == 1
    assert client.get("/api/reports/trends/BM001", headers=user_a).status_code == 404

    # Chat grounded in the member's report only with the matching scope.
    c = client.post(
        "/api/chat",
        json={"message": "What is my hemoglobin?", "report_id": rid, "member_id": m["id"]},
        headers=user_a,
    )
    assert c.status_code == 200 and "11.2" in c.json()["answer"]
    c2 = client.post(
        "/api/chat",
        json={"message": "What is my hemoglobin?", "report_id": rid},
        headers=user_a,
    )
    assert c2.status_code == 200 and "not found" in c2.json()["answer"]

    # Compare across profiles is rejected.
    rid2, _ = _upload_analyze_member(user_a, None, monkeypatch, tmp_path)
    cmp = client.get(
        "/api/reports/compare", params={"a": rid, "b": rid2}, headers=user_a
    )
    assert cmp.status_code == 400

    # Deleting the member removes their reports (owner's report survives).
    assert client.delete(f"/api/family/{m['id']}", headers=user_a).status_code == 200
    assert client.get("/api/reports", headers=user_a).json()[0]["id"] == rid2
    assert (
        client.get("/api/reports", params={"member_id": m["id"]}, headers=user_a).status_code
        == 404
    )
