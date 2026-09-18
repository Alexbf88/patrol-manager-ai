import os
import io
from fastapi import FastAPI, UploadFile, File, Query, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, Any

from backend.database import init_db, salvar_turnos, listar_turnos, obter_resumo, atualizar_turno, purgar_turnos
from backend.parser import processar_chat_whatsapp

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

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
