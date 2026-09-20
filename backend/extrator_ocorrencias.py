import os
import re
import json
import httpx
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from backend.parser import parse_data_hora, identificar_seguranca
from backend.ai_client import chamar_ia_json, get_ai_config

MSG_LINE_REGEX = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}),?\s+(\d{1,2}:\d{2})\s*-\s*([^:]+):\s*(.*)$")

IGNORAR_TERMOS = [
    "iniciando serviço", "iniciando servico", "encerrando serviço", "encerrando servico",
    "reiniciando serviço", "reiniciando servico", "início de trabalho", "inicio de trabalho",
    "saída pra almoço", "saida pra almoco", "saída para almoço", "saida para almoco",
    "rendição", "rendicao", "location: https://maps", "this message was deleted",
    "chamou você", "you deleted this message", "mudou o código de segurança"
]

PALAVRAS_CHAVE_OCORRENCIA = [
    "policia", "polícia", "pm", "viatura", "suspeit", "estranh", "aborda", "preso", "fuga",
    "arvore", "árvore", "galho", "fio", "enel", "luz", "energia", "poste", "fogo", "queimada", "fumaca", "fumaça",
    "cao", "cão", "cachorro", "animal", "cavalo", "gado",
    "cratera", "buraco", "asfalto", "cano", "vazamento", "sabesp",
    "portao", "portão", "alarme", "disparou", "barulho", "som", "musica", "música",
    "carro", "moto", "veiculo", "veículo", "placa", "abandonado",
    "alerta", "atencao", "atenção", "cuidado", "perigo", "aviso", "verificar", "aberto"
]

def formatar_data_br(dt_str: str) -> str:
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return dt_str

def extrair_threads_candidatas(chat_texto: str, data_minima: Optional[datetime] = None) -> List[List[Dict[str, Any]]]:
    linhas = chat_texto.splitlines()
    mensagens = []
    
    for l in linhas:
        m = MSG_LINE_REGEX.match(l)
        if m:
            data_str, hora_str, remetente, mensagem = m.groups()
            dt = parse_data_hora(data_str, hora_str)
            if not dt:
                continue
            if data_minima and dt < data_minima:
                continue
            mensagens.append({
                "datetime": dt,
                "remetente": remetente.strip(),
                "mensagem": mensagem.strip()
            })
        else:
            if mensagens and l.strip():
                mensagens[-1]["mensagem"] += " " + l.strip()
                
    # Filtrar apenas mensagens com potencial de ocorrência
    msgs_filtradas = []
    for m in mensagens:
        txt = m["mensagem"]
        txt_lower = txt.lower()
        
        # Ignora avisos de rotina
        if any(term in txt_lower for term in IGNORAR_TERMOS):
            continue
            
        limpo = txt.replace("<Media omitted>", "").strip()
        # Remove nomes de arquivos anexos (ex: IMG-20260911-WA0032.jpg (file attached))
        texto_sem_anexo = re.sub(r"[\w-]+\.(?:jpg|jpeg|png|opus|mp4|pdf)\s*(?:\(file attached\))?", "", limpo, flags=re.IGNORECASE).strip()
        if not texto_sem_anexo and "(file attached)" in limpo.lower():
            continue
            
        limpo = texto_sem_anexo if texto_sem_anexo else limpo
        limpo_sem_pont = re.sub(r"[^\w\s]", "", limpo).strip()
        
        # Ignora mensagens curtíssimas sem conteúdo (ex: "ok", "obrigado")
        if len(limpo_sem_pont.split()) < 3 and len(limpo) < 12:
            continue
            
        # Considera candidata se tiver palavra-chave OU tiver texto relevante (mais de 20 caracteres)
        tem_keyword = any(k in txt_lower for k in PALAVRAS_CHAVE_OCORRENCIA)
        if tem_keyword or len(limpo) >= 20:
            # Identifica se é segurança conhecido ou morador
            seg = identificar_seguranca(m["remetente"])
            autor_formatado = seg if seg else ("Morador" if m["remetente"].startswith("+") else m["remetente"])
            msgs_filtradas.append({
                "datetime": m["datetime"],
                "remetente": m["remetente"],
                "autor": autor_formatado,
                "texto": limpo
            })
            
    # Agrupar mensagens em conversas/threads próximas no tempo (janela de 25 min)
    threads = []
    curr_thread = []
    
    for m in msgs_filtradas:
        if not curr_thread:
            curr_thread.append(m)
        else:
            if (m["datetime"] - curr_thread[-1]["datetime"]) <= timedelta(minutes=25):
                curr_thread.append(m)
            else:
                threads.append(curr_thread)
                curr_thread = [m]
                
    if curr_thread:
        threads.append(curr_thread)
        
    return threads

async def processar_lote_com_ollama(client: httpx.AsyncClient, batch_threads: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    itens_texto = []
    for idx, th in enumerate(batch_threads, 1):
        dt_str = th[0]["datetime"].strftime("%Y-%m-%d %H:%M")
        conversa = " | ".join([f"{x['autor']}: {x['texto']}" for x in th])
        itens_texto.append(f"Item {idx} [{dt_str}]: {conversa}")
        
    bloco_relatos = "\n".join(itens_texto)
    
    prompt = f"""Você é um auditor e especialista em segurança patrimonial de condomínios e bairros residenciais.
Sua tarefa é analisar as mensagens trocadas no grupo de segurança e EXTRAIR APENAS os eventos que representam ocorrências reais de segurança, infraestrutura urbana, patrulhamento, apoio policial, perturbação de sossego, acidentes, animais soltos, queimadas ou alertas úteis para os moradores.

IGNORE rigorosamente mensagens de bate-papo, piadas, saudações (parabéns, dia dos pais, feliz ano novo, etc.) ou conversas sem evento real.

Mensagens a analisar:
---
{bloco_relatos}
---

Para CADA ocorrência real identificada, extraia:
- data_hora: data e hora aproximada do evento no formato "AAAA-MM-DD HH:MM"
- autor: nome do segurança ou morador que reportou
- categoria: escolha EXATAMENTE uma entre:
  ["Segurança / Suspeito", "Infraestrutura / Vias", "Polícia / Ronda Preventiva", "Perturbação do Sossego / Som", "Animais / Pets", "Outros"]
- severidade: "Alta" (suspeitos, crimes, crateras perigosas, fios partidos, fogo), "Média" (animais na via, som alto, obras, vias bloqueadas), ou "Baixa" (viatura em ronda preventiva de rotina, comunicados normais)
- local: rua, avenida ou ponto de referência citado (ou "Não informado" se não disser)
- descricao: resumo claro, formal e objetivo do fato em português (1 frase)
- mensagem_original: trecho exato ou resumo da mensagem do WhatsApp

Responda ESTRITAMENTE em formato JSON com o seguinte schema:
{{
  "ocorrencias": [
    {{
      "data_hora": "AAAA-MM-DD HH:MM",
      "autor": "Nome",
      "categoria": "Segurança / Suspeito",
      "severidade": "Alta",
      "local": "Local citado",
      "descricao": "Resumo do que ocorreu",
      "mensagem_original": "Texto do relato"
    }}
  ]
}}
Se não houver nenhuma ocorrência relevante no bloco, retorne: {{"ocorrencias": []}}
"""

    try:
        sucesso, parsed, msg_status = await chamar_ia_json(prompt, client=client, timeout=85.0)
        if not sucesso or not isinstance(parsed, dict):
            print(f"Aviso da IA ao extrair ocorrências: {msg_status}")
            return []
            
        ocorrencias = parsed.get("ocorrencias", [])
        
        resultado = []
        for oc in ocorrencias:
            dh = oc.get("data_hora", "")
            m_dt = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", dh)
            if not m_dt:
                dh = batch_threads[0][0]["datetime"].strftime("%Y-%m-%d %H:%M")
            else:
                dh = f"{m_dt.group(1)} {m_dt.group(2)}"
                
            resultado.append({
                "data_hora": dh,
                "data_hora_br": formatar_data_br(dh),
                "autor": oc.get("autor", "Segurança / Morador"),
                "categoria": oc.get("categoria", "Outros"),
                "severidade": oc.get("severidade", "Baixa"),
                "local": oc.get("local", "Não informado"),
                "descricao": oc.get("descricao", "Ocorrência registrada"),
                "mensagem_original": oc.get("mensagem_original", "")
            })
        return resultado
    except Exception as e:
        print(f"Erro ao processar lote no Ollama: {e}")
        return []

async def extrair_todas_ocorrencias(
    chat_texto: str,
    data_minima_str: Optional[str] = "2026-06-01",
    limite_threads: Optional[int] = None
) -> List[Dict[str, Any]]:
    dt_min = None
    if data_minima_str:
        try:
            dt_min = datetime.strptime(data_minima_str, "%Y-%m-%d")
        except Exception:
            pass
            
    threads = extrair_threads_candidatas(chat_texto, data_minima=dt_min)
    if not threads:
        return []
        
    # Se definido limite, processa os mais recentes; senão analisa todos
    if limite_threads and limite_threads > 0:
        threads_para_processar = threads[-limite_threads:]
    else:
        threads_para_processar = threads
    
    TAMANHO_LOTE = 8
    ocorrencias_totais = []
    
    async with httpx.AsyncClient(timeout=95.0) as client:
        for i in range(0, len(threads_para_processar), TAMANHO_LOTE):
            lote = threads_para_processar[i:i + TAMANHO_LOTE]
            oc_lote = await processar_lote_com_ollama(client, lote)
            ocorrencias_totais.extend(oc_lote)
            
    ocorrencias_totais.sort(key=lambda x: x["data_hora"], reverse=True)
    return ocorrencias_totais
