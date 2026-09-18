from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.pipeline import run_pipeline

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_frontend() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "DataBank Explorer" in response.text


def test_missing_results_and_published_contracts(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert client.get("/api/overview").status_code == 503
    assert client.get("/api/facilities").status_code == 503
    example = Path(__file__).resolve().parents[1] / "data" / "raw" / "example"
    run_pipeline(tmp_path, from_snapshot=example)
    overview = client.get("/api/overview")
    assert overview.status_code == 200
    assert overview.json()["summary"]["facility_count"] == 4
    response = client.get("/api/facilities?market=chicago&min_capacity_mw=5")
    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["facilities"][0]["facility_code"] == "ORD4"
    assert client.get("/api/facilities?min_capacity_mw=-1").status_code == 422
    assert client.get("/api/facilities?market=missing").json()["count"] == 0
