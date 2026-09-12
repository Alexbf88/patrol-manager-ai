import sqlite3
import os
from typing import List, Dict, Any, Optional

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "rondas.db"))

def get_db():
    # Garante que a pasta pai exista (ex: /app/data)
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS turnos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seguranca TEXT NOT NULL,
        telefone_origem TEXT,
        veiculo_tipo TEXT,
        veiculo_cor TEXT,
        data_inicio TEXT NOT NULL,
        data_fim TEXT,
        horas_trabalhadas REAL,
        status TEXT NOT NULL,
        detalhes TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(seguranca, data_inicio)
    );
    """)
    conn.commit()
    conn.close()

def salvar_turnos(turnos: List[Dict[str, Any]]) -> int:
    conn = get_db()
    cursor = conn.cursor()
    inseridos = 0
    for t in turnos:
        try:
            cursor.execute("""
            INSERT INTO turnos (
                seguranca, telefone_origem, veiculo_tipo, veiculo_cor,
                data_inicio, data_fim, horas_trabalhadas, status, detalhes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(seguranca, data_inicio) DO UPDATE SET
                data_fim = excluded.data_fim,
                horas_trabalhadas = excluded.horas_trabalhadas,
                status = excluded.status,
                veiculo_tipo = excluded.veiculo_tipo,
                veiculo_cor = excluded.veiculo_cor,
                detalhes = excluded.detalhes
            """, (
                t.get("seguranca"),
                t.get("telefone_origem"),
                t.get("veiculo_tipo"),
                t.get("veiculo_cor"),
                t.get("data_inicio"),
                t.get("data_fim"),
                t.get("horas_trabalhadas"),
                t.get("status"),
                t.get("detalhes")
            ))
            inseridos += 1
        except Exception as e:
            print(f"Erro ao salvar turno: {e}")
    conn.commit()
    conn.close()
    return inseridos

def listar_turnos(seguranca: Optional[str] = None, data_inicio: Optional[str] = None, data_fim: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    
    query = "SELECT * FROM turnos WHERE 1=1"
    params = []
    
    if seguranca:
        query += " AND seguranca LIKE ?"
        params.append(f"%{seguranca}%")
    if data_inicio:
        query += " AND data_inicio >= ?"
        params.append(data_inicio)
    if data_fim:
        query += " AND data_inicio <= ?"
        params.append(data_fim + " 23:59:59")
        
    query += " ORDER BY data_inicio DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def obter_resumo() -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT 
        seguranca,
        COUNT(*) as total_turnos,
        ROUND(SUM(horas_trabalhadas), 2) as total_horas,
        ROUND(AVG(horas_trabalhadas), 2) as media_horas
    FROM turnos
    WHERE horas_trabalhadas IS NOT NULL
    GROUP BY seguranca
    ORDER BY total_horas DESC
    """)
    resumo_segurancas = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT COUNT(*) as total_turnos, ROUND(SUM(horas_trabalhadas), 2) as total_horas FROM turnos")
    geral = dict(cursor.fetchone() or {"total_turnos": 0, "total_horas": 0})
    
    conn.close()
    return {
        "geral": geral,
        "por_seguranca": resumo_segurancas
    }
