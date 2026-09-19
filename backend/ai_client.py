import os
import re
import json
import httpx
from typing import Dict, Any, Tuple, Optional

def get_ai_config() -> Dict[str, str]:
    api_key = os.environ.get("AI_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    provider = os.environ.get("AI_PROVIDER")
    if not provider:
        provider = "openai" if api_key else "ollama"
    provider = provider.lower().strip()

    if provider in ["openai", "cloud"]:
        base_url = os.environ.get("AI_BASE_URL") or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.environ.get("AI_MODEL", "gpt-4o-mini")
    else:
        base_url = os.environ.get("AI_BASE_URL") or os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
        model = os.environ.get("AI_MODEL") or os.environ.get("OLLAMA_MODEL", "llama3.1:latest")

    return {
        "provider": provider,
        "base_url": base_url.rstrip("/"),
        "model": model,
        "api_key": api_key,
    }

def limpar_json_resposta(texto: str) -> Any:
    texto = texto.strip()
    if texto.startswith("```"):
        texto = re.sub(r"^```(?:json)?\s*", "", texto)
        texto = re.sub(r"\s*```$", "", texto)
    return json.loads(texto)

async def chamar_ia_json(
    prompt: str,
    system_prompt: str = "Você é um assistente prestativo que responde exclusivamente em formato JSON válido.",
    timeout: float = 90.0,
    client: Optional[httpx.AsyncClient] = None
) -> Tuple[bool, Any, str]:
    """
    Executa a chamada de IA de forma unificada suportando:
    - Ollama Local (nativo ou custom endpoint)
    - Provedores Nuvem compatíveis com OpenAI (OpenAI, Groq, OpenRouter, DeepSeek, Together, vLLM, etc.) via Token/API Key
    
    Retorna: (sucesso: bool, resultado_json: dict/list, mensagem_status: str)
    """
    cfg = get_ai_config()
    provider = cfg["provider"]
    base_url = cfg["base_url"]
    model = cfg["model"]
    api_key = cfg["api_key"]

    should_close = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout)
        should_close = True

    try:
        if provider in ["openai", "cloud"]:
            # Endpoint OpenAI Chat Completions padrão
            url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1
            }
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                return False, None, f"Erro na API Cloud ({resp.status_code}): {resp.text}"
            
            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"]
            parsed = limpar_json_resposta(raw_content)
            return True, parsed, f"Sucesso via {provider} ({model})"

        else:
            # Endpoint Ollama nativo
            url = f"{base_url}/api/generate" if not base_url.endswith("/api/generate") else base_url
            payload = {
                "model": model,
                "prompt": prompt,
                "format": "json",
                "stream": False
            }
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                return False, None, f"Erro na API Ollama ({resp.status_code}): {resp.text}"

            data = resp.json()
            raw_content = data.get("response", "{}")
            parsed = limpar_json_resposta(raw_content)
            return True, parsed, f"Sucesso via Ollama ({model})"

    except httpx.ConnectError:
        msg = f"Falha de conexão com endpoint de IA ({base_url}). Verifique se o serviço/host está acessível."
        return False, None, msg
    except json.JSONDecodeError as e:
        return False, None, f"A IA retornou um JSON inválido: {e}"
    except Exception as e:
        return False, None, f"Falha na execução com IA: {str(e)}"
    finally:
        if should_close:
            await client.aclose()
