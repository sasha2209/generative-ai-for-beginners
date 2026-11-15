import json
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from fhg.api import Settings, create_app

SAMPLES = Path(__file__).parent.parent / "fhg" / "sample_data"


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=str(tmp_path / "test.db"), encryption_key=Fernet.generate_key().decode(),
                    admin_key="admin-secret", pseudonym_secret="pepper")


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


def new_user(client):
    r = client.post("/v1/users")
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_auth_required(client):
    assert client.get("/v1/profile").status_code == 401
    assert client.get("/v1/profile", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_full_flow(client):
    h = new_user(client)
    bundle = json.loads((SAMPLES / "fhir_bundle.json").read_text())
    r = client.post("/v1/ingest/fhir", json=bundle, headers=h)
    assert r.status_code == 200 and r.json()["merged"]["relatives_added"] == 6

    # The same history typed as text merges into the existing relatives.
    r = client.post("/v1/ingest/text", json={"text": (SAMPLES / "family_history.txt").read_text()}, headers=h)
    assert r.json()["merged"]["relatives_added"] == 0

    profile = client.get("/v1/profile", headers=h).json()
    assert len(profile["family"]) == 6

    insights = client.get("/v1/insights", headers=h).json()
    ids = [i["rule_id"] for i in insights["insights"]]
    assert ids[0] == "premature_ascvd_family_history"
    assert "hboc_family_pattern" in ids and "colorectal_family_history" not in ids
    assert insights["disclaimer"]

    summary = client.get("/v1/insights/summary", headers=h).json()
    assert summary["generated_by"] == "template"

    assert len(client.get("/v1/ingests", headers=h).json()) == 2
    actions = [a["action"] for a in client.get("/v1/audit", headers=h).json()]
    assert "ingest.fhir" in actions and "insights.generated" in actions


def test_preview_does_not_save(client):
    h = new_user(client)
    r = client.post("/v1/ingest/text?preview=true", json={"text": "My dad had a stroke at 50."}, headers=h)
    assert r.json()["preview"] is True
    assert r.json()["parsed"]["family"][0]["relationship"] == "father"
    assert client.get("/v1/profile", headers=h).json()["family"] == []


def test_manual_entry_and_delete(client):
    h = new_user(client)
    r = client.post("/v1/family", json={"relationship": "brother",
                                        "conditions": [{"name": "heart attack", "onset_age": 41}]}, headers=h)
    assert r.status_code == 201
    client.post("/v1/observations", json={"code": "LDL", "value": 150, "unit": "mg/dL"}, headers=h)
    ids = [i["rule_id"] for i in client.get("/v1/insights", headers=h).json()["insights"]]
    assert "premature_ascvd_family_history" in ids
    member_id = client.get("/v1/profile", headers=h).json()["family"][0]["id"]
    assert client.delete(f"/v1/family/{member_id}", headers=h).status_code == 204
    assert client.delete(f"/v1/family/{member_id}", headers=h).status_code == 404


def test_users_are_isolated(client):
    a, b = new_user(client), new_user(client)
    client.post("/v1/ingest/text", json={"text": "My mother had breast cancer at 40."}, headers=a)
    assert client.get("/v1/profile", headers=b).json()["family"] == []


def test_data_is_encrypted_at_rest(client, settings):
    h = new_user(client)
    client.post("/v1/ingest/text", json={"text": "My mother had ovarian cancer at 52."}, headers=h)
    raw = sqlite3.connect(settings.db_path).execute("SELECT data FROM profiles").fetchone()[0]
    assert b"ovarian" not in raw
    raw_ingest = sqlite3.connect(settings.db_path).execute("SELECT raw FROM ingest_events").fetchone()[0]
    assert b"ovarian" not in raw_ingest


def test_partner_sharing_requires_consent_and_minimum_necessary(client):
    h = new_user(client)
    client.post("/v1/ingest/fhir", json=json.loads((SAMPLES / "fhir_bundle.json").read_text()), headers=h)
    assert client.post("/v1/partners/health-plan/share", headers=h).status_code == 403
    client.post("/v1/consents", json={"scope": "share:health-plan", "granted": True}, headers=h)
    payload = client.post("/v1/partners/health-plan/share", headers=h).json()["payload"]
    assert "fhir_bundle" not in payload  # health plan only receives insights
    assert payload["insights"]

    client.post("/v1/consents", json={"scope": "share:health-plan", "granted": False}, headers=h)
    assert client.post("/v1/partners/health-plan/share", headers=h).status_code == 403
    assert client.post("/v1/consents", json={"scope": "share:anyone", "granted": True}, headers=h).status_code == 422


def test_research_export_deidentified_and_consented(client):
    consenting, other = new_user(client), new_user(client)
    for h in (consenting, other):
        client.post("/v1/ingest/fhir", json=json.loads((SAMPLES / "fhir_bundle.json").read_text()), headers=h)
    client.post("/v1/consents", json={"scope": "research_deidentified", "granted": True}, headers=consenting)

    assert client.get("/admin/research/export").status_code == 403
    assert client.get("/admin/research/export", headers={"X-Admin-Key": "wrong"}).status_code == 403
    data = client.get("/admin/research/export", headers={"X-Admin-Key": "admin-secret"}).json()
    assert data["count"] == 1
    rec = data["records"][0]
    assert rec["birth_year"] == 1984 and "birth_date" not in rec
    assert "1984-05-02" not in json.dumps(rec)


def test_delete_account(client):
    h = new_user(client)
    client.post("/v1/ingest/text", json={"text": "My mother had breast cancer at 40."}, headers=h)
    assert client.delete("/v1/me", headers=h).status_code == 204
    assert client.get("/v1/profile", headers=h).status_code == 401


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Family Health Graph" in r.text
