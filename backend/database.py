import sqlite3
import os
from typing import List, Dict, Any, Optional

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "rondas.db"))

def get_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
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
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ocorrencias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data_hora TEXT NOT NULL,
        data_hora_br TEXT,
        autor TEXT,
        categoria TEXT NOT NULL,
        severidade TEXT NOT NULL,
        local TEXT,
        descricao TEXT NOT NULL,
        mensagem_original TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(data_hora, autor, descricao)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ocorrencias_data ON ocorrencias(data_hora);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ocorrencias_severidade ON ocorrencias(severidade);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ocorrencias_categoria ON ocorrencias(categoria);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_turnos_data_inicio ON turnos(data_inicio DESC);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_turnos_seguranca ON turnos(seguranca);")
    conn.commit()
    conn.close()

def purgar_turnos() -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM turnos")
    removidos = cursor.rowcount
    conn.commit()
    conn.close()
    return removidos

def remover_seguranca(nome_seguranca: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM turnos WHERE seguranca = ?", (nome_seguranca,))
    removidos = cursor.rowcount
    conn.commit()
    conn.close()
    return removidos

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
        params.append(data_inicio + " 00:00:00")
    if data_fim:
        query += " AND data_inicio <= ?"
        params.append(data_fim + " 23:59:59")
        
    query += " ORDER BY data_inicio DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def obter_resumo(seguranca: Optional[str] = None, data_inicio: Optional[str] = None, data_fim: Optional[str] = None) -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()
    
    where = "WHERE 1=1"
    params = []
    
    if seguranca:
        where += " AND seguranca LIKE ?"
        params.append(f"%{seguranca}%")
    if data_inicio:
        where += " AND data_inicio >= ?"
        params.append(data_inicio + " 00:00:00")
    if data_fim:
        where += " AND data_inicio <= ?"
        params.append(data_fim + " 23:59:59")
    
    cursor.execute(f"""
    SELECT 
        seguranca,
        COUNT(*) as total_turnos,
        ROUND(SUM(horas_trabalhadas), 2) as total_horas,
        ROUND(AVG(horas_trabalhadas), 2) as media_horas
    FROM turnos
    {where} AND horas_trabalhadas IS NOT NULL
    GROUP BY seguranca
    ORDER BY total_horas DESC
    """, params)
    resumo_segurancas = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute(f"SELECT COUNT(*) as total_turnos, ROUND(SUM(horas_trabalhadas), 2) as total_horas FROM turnos {where}", params)
    geral = dict(cursor.fetchone() or {"total_turnos": 0, "total_horas": 0})
    
    conn.close()
    return {
        "geral": geral,
        "por_seguranca": resumo_segurancas
    }

def atualizar_turno(turno_id: int, data_inicio: str, data_fim: Optional[str], horas: Optional[float], status: str, detalhes: Optional[str]):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE turnos SET
        data_inicio = ?,
        data_fim = ?,
        horas_trabalhadas = ?,
        status = ?,
        detalhes = ?
    WHERE id = ?
    """, (data_inicio, data_fim, horas, status, detalhes, turno_id))
    afetados = cursor.rowcount
    conn.commit()
    conn.close()
    return afetados > 0

def obter_turno_por_id(turno_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM turnos WHERE id = ?", (turno_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# ----------------- OCORRÊNCIAS -----------------

def salvar_ocorrencias(ocorrencias: List[Dict[str, Any]]) -> int:
    conn = get_db()
    cursor = conn.cursor()
    inseridos = 0
    for o in ocorrencias:
        try:
            cursor.execute("""
            INSERT OR IGNORE INTO ocorrencias (
                data_hora, data_hora_br, autor, categoria, severidade, local, descricao, mensagem_original
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                o.get("data_hora"),
                o.get("data_hora_br"),
                o.get("autor"),
                o.get("categoria"),
                o.get("severidade"),
                o.get("local"),
                o.get("descricao"),
                o.get("mensagem_original")
            ))
            if cursor.rowcount > 0:
                inseridos += 1
        except Exception as e:
            print(f"Erro ao salvar ocorrencia: {e}")
    conn.commit()
    conn.close()
    return inseridos

def listar_ocorrencias(
    categoria: Optional[str] = None,
    severidade: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    busca: Optional[str] = None
) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    
    filtros = []
    params = []
    
    if categoria:
        filtros.append("categoria = ?")
        params.append(categoria)
        
    if severidade:
        filtros.append("severidade = ?")
        params.append(severidade)
        
    if data_inicio:
        filtros.append("data_hora >= ?")
        params.append(f"{data_inicio} 00:00")
        
    if data_fim:
        filtros.append("data_hora <= ?")
        params.append(f"{data_fim} 23:59")
        
    if busca:
        filtros.append("(descricao LIKE ? OR local LIKE ? OR autor LIKE ? OR mensagem_original LIKE ?)")
        termo = f"%{busca}%"
        params.extend([termo, termo, termo, termo])
        
    where = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    query = f"SELECT * FROM ocorrencias {where} ORDER BY data_hora DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def obter_resumo_ocorrencias() -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as total FROM ocorrencias")
    total = cursor.fetchone()["total"]
    
    cursor.execute("""
    SELECT severidade, COUNT(*) as qtd 
    FROM ocorrencias 
    GROUP BY severidade
    """)
    por_sev = {r["severidade"]: r["qtd"] for r in cursor.fetchall()}
    
    cursor.execute("""
    SELECT categoria, COUNT(*) as qtd 
    FROM ocorrencias 
    GROUP BY categoria 
    ORDER BY qtd DESC
    """)
    por_cat = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    return {
        "total": total,
        "por_severidade": {
            "Alta": por_sev.get("Alta", 0),
            "Média": por_sev.get("Média", 0),
            "Baixa": por_sev.get("Baixa", 0)
        },
        "por_categoria": por_cat
    }

def deletar_ocorrencia(ocorrencia_id: int) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ocorrencias WHERE id = ?", (ocorrencia_id,))
    afetados = cursor.rowcount
    conn.commit()
    conn.close()
    return afetados > 0

def purgar_ocorrencias() -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ocorrencias")
    removidos = cursor.rowcount
    conn.commit()
    conn.close()
    return removidos

