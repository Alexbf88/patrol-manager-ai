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

def test_upload_and_purgar():
    chat_content = b"""27/08/2026, 06:00 - Marcos Silva: Iniciando servico Marcos Silva
27/08/2026, 18:00 - Marcos Silva: Encerrando servico
"""
    # Test upload
    response = client.post(
        "/api/upload",
        files={"file": ("test_chat.txt", chat_content, "text/plain")}
    )
    assert response.status_code == 200
    data = response.json()
    assert "processados com sucesso" in data["mensagem"]

    # Test resumo
    resumo_resp = client.get("/api/resumo")
    assert resumo_resp.status_code == 200
    assert "geral" in resumo_resp.json()

    # Test list turnos
    turnos_resp = client.get("/api/turnos")
    assert turnos_resp.status_code == 200
    turnos = turnos_resp.json()
    assert len(turnos) >= 1
    turno_id = turnos[0]["id"]

    # Test update turno
    put_resp = client.put(f"/api/turnos/{turno_id}", json={
        "data_inicio": "2026-08-27 06:00",
        "data_fim": "2026-08-27 17:00",
        "detalhes": "Ajuste manual de teste"
    })
    assert put_resp.status_code == 200
    assert put_resp.json()["horas_trabalhadas"] == 11.0

    # Test purgar
    purge_resp = client.post("/api/purgar")
    assert purge_resp.status_code == 200
    assert purge_resp.json()["removidos"] >= 1
