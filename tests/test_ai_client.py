import pytest
import httpx
from unittest.mock import patch, AsyncMock
from backend.ai_client import get_ai_config, chamar_ia_json, limpar_json_resposta

def test_limpar_json_resposta():
    raw_markdown = """```json
    {
        "chave": "valor",
        "numero": 42
    }
    ```"""
    res = limpar_json_resposta(raw_markdown)
    assert res == {"chave": "valor", "numero": 42}

def test_get_ai_config_default(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:latest")

    cfg = get_ai_config()
    assert cfg["provider"] == "ollama"
    assert cfg["base_url"] == "http://localhost:11434"
    assert cfg["model"] == "llama3.1:latest"
    assert cfg["api_key"] == ""

def test_get_ai_config_cloud_auto_detect(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.setenv("AI_API_KEY", "sk-test-token-123")
    monkeypatch.setenv("AI_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("AI_MODEL", "llama-3.1-70b-versatile")

    cfg = get_ai_config()
    assert cfg["provider"] == "openai"
    assert cfg["base_url"] == "https://api.groq.com/openai/v1"
    assert cfg["model"] == "llama-3.1-70b-versatile"
    assert cfg["api_key"] == "sk-test-token-123"

@pytest.mark.anyio
async def test_chamar_ia_json_cloud_mock(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("AI_MODEL", "gpt-4o-mini")

    dummy_request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    mock_resp = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": '{"data_fim_sugerida": "2026-08-20 18:00", "confianca": "Alta"}'
                    }
                }
            ]
        },
        request=dummy_request
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        sucesso, data, msg = await chamar_ia_json("Analise o turno")
        assert sucesso is True, f"Failed with: {msg}"
        assert data["data_fim_sugerida"] == "2026-08-20 18:00"
        assert data["confianca"] == "Alta"

@pytest.mark.anyio
async def test_chamar_ia_json_cloud_fallback_without_response_format(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("AI_MODEL", "custom-model")

    dummy_request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    # First call with response_format fails with 400
    fail_resp = httpx.Response(400, text="response_format is not supported by this model", request=dummy_request)
    # Second fallback call succeeds with 200
    ok_resp = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": '{"data_fim_sugerida": "2026-08-20 19:00", "confianca": "Média"}'
                    }
                }
            ]
        },
        request=dummy_request
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [fail_resp, ok_resp]
        sucesso, data, msg = await chamar_ia_json("Analise o turno")
        assert sucesso is True, f"Failed with: {msg}"
        assert data["data_fim_sugerida"] == "2026-08-20 19:00"
        assert data["confianca"] == "Média"
        assert mock_post.call_count == 2
