import os
import re
import json
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:latest")

async def auditar_turno_com_ollama(turno: Dict[str, Any], mensagens_chat: list) -> Dict[str, Any]:
    seguranca = turno["seguranca"]
    data_inicio_str = turno["data_inicio"]
    
    dt_inicio = datetime.strptime(data_inicio_str, "%Y-%m-%d %H:%M")
    
    # Selecionar mensagens relevantes entre 30 min antes do início e até 24h após
    limite_inicio = dt_inicio - timedelta(minutes=30)
    limite_fim = dt_inicio + timedelta(hours=24)
    primeiro_nome = seguranca.lower().split()[0]
    
    msgs_relevantes = []
    for m in mensagens_chat:
        dt_m = m.get("datetime")
        if not dt_m or not (limite_inicio <= dt_m <= limite_fim):
            continue
        msg_txt = m.get("mensagem", "")
        rem = m.get("seguranca")
        # Inclui mensagens enviadas pelo próprio segurança ou mensagens que mencionam o nome dele
        if rem == seguranca or primeiro_nome in msg_txt.lower():
            rem_label = rem or m.get("remetente", "Desconhecido")
            msgs_relevantes.append(f"[{dt_m.strftime('%d/%m %H:%M')}] {rem_label}: {msg_txt}")
                
    if not msgs_relevantes:
        return {
            "sucesso": False,
            "mensagem": "Não foram encontradas mensagens do segurança para este dia."
        }
        
    contexto_msgs = "\n".join(msgs_relevantes[-20:]) # Até 20 mensagens mais recentes do turno
    
    prompt = f"""Você é um auditor de turnos de segurança patrimonial.
O segurança '{seguranca}' iniciou o plantão em {dt_inicio.strftime('%d/%m/%Y %H:%M')}.
No entanto, o encerramento do turno precisa ser verificado e auditado.
Abaixo estão as mensagens e relatos daquele período (incluindo legendas de fotos e comentários):

---
{contexto_msgs}
---

Instruções:
1. Analise cuidadosamente o texto de cada mensagem e legenda.
2. REGRA CRÍTICA DE HORÁRIO: Se o segurança enviou uma foto ou mensagem dizendo 'encerrando as 16.45', 'encerrado às 16:30', etc., o horário real de encerramento DEVE SER o horário citado no texto (ex: 16:45), e NUNCA o horário de envio da foto/mensagem.
3. Se não houver menção explícita de horário retroativo no texto, use o horário de envio da última foto ou atividade daquele plantão.
4. "data_fim_sugerida" DEVE conter a data do plantão ({dt_inicio.strftime('%Y-%m-%d')}) e o horário real de encerramento no formato "AAAA-MM-DD HH:MM".
5. Forneça uma justificativa concisa em português explicando de onde veio o horário.
6. Classifique a confiança como "Alta" (se mencionado no texto/legenda), "Média" (se baseado no horário da foto) ou "Baixa".

Responda ESTRITAMENTE em formato JSON com o seguinte schema:
{{
  "data_fim_sugerida": "{dt_inicio.strftime('%Y-%m-%d')} HH:MM",
  "justificativa": "Texto explicativo curto",
  "confianca": "Alta"
}}
"""

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                }
            )
            
            if resp.status_code != 200:
                return {
                    "sucesso": False,
                    "mensagem": f"Erro na resposta do Ollama: HTTP {resp.status_code}"
                }
                
            data = resp.json()
            resposta_texto = data.get("response", "{}").strip()
            if resposta_texto.startswith("```"):
                resposta_texto = re.sub(r"^```(?:json)?\s*", "", resposta_texto)
                resposta_texto = re.sub(r"\s*```$", "", resposta_texto)
            resultado_json = json.loads(resposta_texto)
            
            # Validação simples do retorno
            data_fim_sug = resultado_json.get("data_fim_sugerida")
            justificativa = resultado_json.get("justificativa", "Sugerido por auditoria de IA")
            confianca = resultado_json.get("confianca", "Média")
            
            return {
                "sucesso": True,
                "data_inicio": data_inicio_str,
                "data_fim_sugerida": data_fim_sug,
                "justificativa": justificativa,
                "confianca": confianca,
                "modelo_usado": OLLAMA_MODEL
            }
            
    except httpx.ConnectError:
        return {
            "sucesso": False,
            "mensagem": f"Não foi possível conectar ao Ollama em {OLLAMA_BASE_URL}. Verifique se o serviço está rodando no host."
        }
    except Exception as e:
        return {
            "sucesso": False,
            "mensagem": f"Falha na auditoria com Ollama: {str(e)}"
        }
