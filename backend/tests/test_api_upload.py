from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import get_db
from app.main import app


class FakeSession:
    def __init__(self) -> None:
        self.documents = []
        self.attempts = []

    def add_all(self, documents) -> None:
        for document in documents:
            document.created_at = datetime.now(UTC)
        self.documents.extend(documents)

    def add(self, item) -> None:
        self.attempts.append(item)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


@pytest.fixture
def api_client(monkeypatch, tmp_path):
    session = FakeSession()
    monkeypatch.setattr("app.main.create_database_schema", lambda: None)
    monkeypatch.setattr(
        "app.api.get_settings",
        lambda: SimpleNamespace(upload_dir=tmp_path, max_upload_bytes=10),
    )
    monkeypatch.setattr("app.api._queue_processing", lambda _document_id: None)
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_upload_stores_file_and_returns_queued_document(api_client, tmp_path) -> None:
    response = api_client.post(
        "/api/documents/upload",
        files={"files": ("invoice.csv", b"a,b\n1,2\n", "text/csv")},
    )

    assert response.status_code == 202
    result = response.json()[0]
    assert result["original_filename"] == "invoice.csv"
    assert result["status"] == "queued"
    assert (tmp_path / f"{result['id']}.csv").read_bytes() == b"a,b\n1,2\n"


def test_upload_rejects_unsupported_extension(api_client) -> None:
    response = api_client.post(
        "/api/documents/upload",
        files={"files": ("invoice.exe", b"nope", "application/octet-stream")},
    )

    assert response.status_code == 415


def test_upload_removes_oversized_partial_file(api_client, tmp_path) -> None:
    response = api_client.post(
        "/api/documents/upload",
        files={"files": ("invoice.csv", b"01234567890", "text/csv")},
    )

    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []
