from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_healthz_endpoint():
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "patrol-manager-ai"

def test_readyz_endpoint():
    response = client.get("/readyz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"

def test_get_turnos():
    response = client.get("/api/turnos")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_get_ocorrencias():
    response = client.get("/api/ocorrencias")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
