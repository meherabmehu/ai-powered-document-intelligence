from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint(monkeypatch) -> None:
    monkeypatch.setattr("app.main.create_database_schema", lambda: None)
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
