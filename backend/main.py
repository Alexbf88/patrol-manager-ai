import os
import io
from fastapi import FastAPI, UploadFile, File, Query, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, Any

from backend.database import (
    init_db, salvar_turnos, listar_turnos, obter_resumo, atualizar_turno, purgar_turnos, obter_turno_por_id,
    salvar_ocorrencias, listar_ocorrencias, obter_resumo_ocorrencias, deletar_ocorrencia, purgar_ocorrencias
)
from backend.parser import processar_chat_whatsapp, extrair_mensagens_chat
from backend.auditor_ia import auditar_turno_com_ollama
from backend.extrator_ocorrencias import extrair_todas_ocorrencias

CHAT_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ultimo_chat.txt")

app = FastAPI(title="Ronda Segurança API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    init_db()

def formatar_data_br(data_iso_str: Optional[str]) -> str:
    if not data_iso_str:
        return "-"
    try:
        dt = datetime.strptime(data_iso_str, "%Y-%m-%d %H:%M")
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return data_iso_str

def formatar_horas_hm(horas_decimal: Optional[float]) -> str:
    if horas_decimal is None or horas_decimal < 0:
        return "-"
    total_minutos = round(horas_decimal * 60)
    h = total_minutos // 60
    m = total_minutos % 60
    if h > 0 and m > 0:
        return f"{h}h{m:02d}m"
    elif h > 0:
        return f"{h}h"
    else:
        return f"{m}m"

@app.post("/api/upload")
async def upload_chat(file: UploadFile = File(...)):
    if not file.filename.endswith(('.txt', '.log')):
        raise HTTPException(status_code=400, detail="Apenas arquivos de texto (.txt) do WhatsApp são permitidos.")
        
    conteudo = await file.read()
    try:
        texto = conteudo.decode("utf-8")
    except UnicodeDecodeError:
        try:
            texto = conteudo.decode("latin-1")
        except Exception:
            raise HTTPException(status_code=400, detail="Erro ao decodificar arquivo. Envie em formato UTF-8.")
            
    # Salvar cache local para possibilitar auditoria por IA das mensagens daquele dia
    try:
        os.makedirs(os.path.dirname(CHAT_CACHE_PATH), exist_ok=True)
        with open(CHAT_CACHE_PATH, "w", encoding="utf-8") as f:
            f.write(texto)
    except Exception as e:
        print(f"Aviso ao salvar cache do chat: {e}")

    turnos = processar_chat_whatsapp(texto)
    total_salvos = salvar_turnos(turnos)
    
    return {
        "mensagem": f"{len(turnos)} turnos processados com sucesso!",
        "total_registrados": total_salvos
    }

@app.post("/api/purgar")
def post_purgar():
    removidos = purgar_turnos()
    return {"mensagem": f"Base de dados purgada com sucesso! {removidos} turnos removidos.", "removidos": removidos}

@app.post("/api/turnos/{turno_id}/auditar-ia")
async def rota_auditar_ia(turno_id: int):
    turno = obter_turno_por_id(turno_id)
    if not turno:
        raise HTTPException(status_code=404, detail="Turno não encontrado.")
        
    if not os.path.exists(CHAT_CACHE_PATH):
        raise HTTPException(
            status_code=400, 
            detail="Arquivo de conversa não encontrado no cache. Faça o upload do arquivo .txt no topo da tela para habilitar a auditoria com IA."
        )
        
    try:
        with open(CHAT_CACHE_PATH, "r", encoding="utf-8") as f:
            chat_texto = f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao ler arquivo de chat em cache: {e}")
        
    mensagens = extrair_mensagens_chat(chat_texto)
    resultado = await auditar_turno_com_ollama(turno, mensagens)
    
    if not resultado.get("sucesso"):
        raise HTTPException(status_code=500, detail=resultado.get("mensagem", "Erro desconhecido na auditoria."))
        
    return resultado

@app.get("/api/turnos")
def get_turnos(
    seguranca: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None)
):
    turnos = listar_turnos(seguranca=seguranca, data_inicio=data_inicio, data_fim=data_fim)
    for t in turnos:
        t["data_inicio_br"] = formatar_data_br(t.get("data_inicio"))
        t["data_fim_br"] = formatar_data_br(t.get("data_fim"))
        t["horas_formatadas"] = formatar_horas_hm(t.get("horas_trabalhadas"))
    return turnos

@app.put("/api/turnos/{turno_id}")
def put_turno(turno_id: int, payload: Dict[str, Any] = Body(...)):
    # Permite ajuste manual de horário pelo gestor
    data_inicio = payload.get("data_inicio")
    data_fim = payload.get("data_fim")
    detalhes = payload.get("detalhes", "Ajuste manual pelo gestor")
    
    if not data_inicio:
        raise HTTPException(status_code=400, detail="data_inicio é obrigatória.")
        
    horas = None
    if data_fim:
        try:
            dt_i = datetime.strptime(data_inicio, "%Y-%m-%d %H:%M")
            dt_f = datetime.strptime(data_fim, "%Y-%m-%d %H:%M")
            horas = round((dt_f - dt_i).total_seconds() / 3600, 2)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Formato de data inválido: {e}")
            
    status = payload.get("status", "Ajustado Manualmente")
    sucesso = atualizar_turno(turno_id, data_inicio, data_fim, horas, status, detalhes)
    if not sucesso:
        raise HTTPException(status_code=404, detail="Turno não encontrado.")
        
    return {"mensagem": "Turno atualizado com sucesso!", "horas_trabalhadas": horas, "horas_formatadas": formatar_horas_hm(horas)}

@app.get("/api/resumo")
def get_resumo(
    seguranca: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None)
):
    resumo = obter_resumo(seguranca=seguranca, data_inicio=data_inicio, data_fim=data_fim)
    if resumo.get("geral"):
        resumo["geral"]["total_horas_formatadas"] = formatar_horas_hm(resumo["geral"].get("total_horas"))
    for s in resumo.get("por_seguranca", []):
        s["total_horas_formatadas"] = formatar_horas_hm(s.get("total_horas"))
        s["media_horas_formatadas"] = formatar_horas_hm(s.get("media_horas"))
    return resumo

@app.get("/api/exportar")
def exportar_excel(
    seguranca: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None)
):
    turnos = listar_turnos(seguranca=seguranca, data_inicio=data_inicio, data_fim=data_fim)
    if not turnos:
        raise HTTPException(status_code=404, detail="Nenhum dado encontrado para exportar.")
        
    for t in turnos:
        t["data_inicio"] = formatar_data_br(t.get("data_inicio"))
        t["data_fim"] = formatar_data_br(t.get("data_fim"))
        t["duracao_formatada"] = formatar_horas_hm(t.get("horas_trabalhadas"))

    df = pd.DataFrame(turnos)
    
    colunas_renomeadas = {
        "id": "ID",
        "seguranca": "Segurança",
        "telefone_origem": "Telefone / Contato",
        "veiculo_tipo": "Tipo Veículo",
        "veiculo_cor": "Cor Veículo",
        "data_inicio": "Início Turno (DD/MM/AAAA HH:MM)",
        "data_fim": "Fim Turno (DD/MM/AAAA HH:MM)",
        "duracao_formatada": "Duração (Horas e Minutos)",
        "horas_trabalhadas": "Horas (Decimal)",
        "status": "Status",
        "detalhes": "Mensagens Originais"
    }
    df = df.rename(columns=colunas_renomeadas)
    
    if "created_at" in df.columns:
        df = df.drop(columns=["created_at"])
        
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Rondas")
    output.seek(0)
    
    headers = {
        "Content-Disposition": "attachment; filename=relatorio_rondas_br.xlsx"
    }
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )

# ----------------- ROTAS DE OCORRÊNCIAS (LIVRO DIGITAL) -----------------

@app.post("/api/ocorrencias/extrair")
async def rota_extrair_ocorrencias(data_minima: Optional[str] = Query("2026-06-01")):
    if not os.path.exists(CHAT_CACHE_PATH):
        raise HTTPException(
            status_code=400,
            detail="Nenhum arquivo de chat carregado. Faça o upload do arquivo .txt primeiro."
        )
        
    try:
        with open(CHAT_CACHE_PATH, "r", encoding="utf-8") as f:
            chat_texto = f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao ler arquivo de chat: {e}")
        
    ocorrencias = await extrair_todas_ocorrencias(chat_texto, data_minima_str=data_minima)
    total_inseridos = salvar_ocorrencias(ocorrencias)
    
    return {
        "sucesso": True,
        "mensagem": f"{len(ocorrencias)} ocorrências analisadas pela IA e sincronizadas!",
        "novas_inseridas": total_inseridos,
        "total_encontradas": len(ocorrencias)
    }

@app.get("/api/ocorrencias")
def get_ocorrencias(
    categoria: Optional[str] = Query(None),
    severidade: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
    busca: Optional[str] = Query(None)
):
    return listar_ocorrencias(
        categoria=categoria,
        severidade=severidade,
        data_inicio=data_inicio,
        data_fim=data_fim,
        busca=busca
    )

@app.get("/api/ocorrencias/resumo")
def get_ocorrencias_resumo():
    return obter_resumo_ocorrencias()

@app.delete("/api/ocorrencias/{ocorrencia_id}")
def delete_ocorrencia(ocorrencia_id: int):
    sucesso = deletar_ocorrencia(ocorrencia_id)
    if not sucesso:
        raise HTTPException(status_code=404, detail="Ocorrência não encontrada.")
    return {"mensagem": "Ocorrência removida com sucesso."}

@app.post("/api/ocorrencias/purgar")
def post_purgar_ocorrencias():
    removidos = purgar_ocorrencias()
    return {"mensagem": f"Livro de ocorrências limpo com sucesso! {removidos} registros removidos.", "removidos": removidos}

@app.get("/api/ocorrencias/exportar")
def exportar_ocorrencias_excel(
    categoria: Optional[str] = Query(None),
    severidade: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
    busca: Optional[str] = Query(None)
):
    ocorrencias = listar_ocorrencias(
        categoria=categoria,
        severidade=severidade,
        data_inicio=data_inicio,
        data_fim=data_fim,
        busca=busca
    )
    if not ocorrencias:
        raise HTTPException(status_code=404, detail="Nenhuma ocorrência encontrada para exportar.")
        
    df = pd.DataFrame(ocorrencias)
    
    colunas_renomeadas = {
        "id": "ID",
        "data_hora_br": "Data e Hora",
        "severidade": "Severidade",
        "categoria": "Categoria",
        "local": "Local / Ponto de Referência",
        "autor": "Relatado Por",
        "descricao": "Descrição Resumida (IA)",
        "mensagem_original": "Mensagem Original WhatsApp"
    }
    df = df.rename(columns=colunas_renomeadas)
    colunas_finais = [c for c in colunas_renomeadas.values() if c in df.columns]
    df = df[colunas_finais]
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Livro_de_Ocorrencias")
    output.seek(0)
    
    headers = {
        "Content-Disposition": "attachment; filename=livro_de_ocorrencias.xlsx"
    }
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
