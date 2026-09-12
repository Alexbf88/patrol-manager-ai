import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

MSG_PATTERN = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}),?\s+(\d{1,2}:\d{2})\s*-\s*([^:]+):\s*(.*)$"
)

# Mapeamento estrito da EQUIPE OFICIAL DE SEGURANÇAS:
# Apenas os 5 seguranças de campo:
# - Marcos Silva (+55 11 99999-0001)
# - Carlos Oliveira (+55 11 99999-0002)
# - Alexandre Santos (+55 11 99999-0003 / Alexandre Santos)
# - Eduardo Lima (Eduardo Lima / Eduardo Lima)
# - Lucas Ferreira (+55 15 99999-0004)
MAPA_CONTATOS = {
    "+55 11 99999-0001": "Marcos Silva",
    "+55 11 99999-0002": "Carlos Oliveira",
    "+55 11 99999-0003": "Alexandre Santos",
    "+55 11 999990001": "Alexandre Santos",
    "Alexandre Santos": "Alexandre Santos",
    "+55 15 99999-0004": "Lucas Ferreira",
    "Eduardo Lima": "Eduardo Lima",
    "Eduardo Lima": "Eduardo Lima"
}

# Remetentes expressamente ignorados (portaria, avisos administrativos, etc.)
REMETENTES_IGNORADOS = {
    "Servicos Gerais - Terceirizado",
    "+55 11 99999-0005",
    "Administracao"
}

def parse_data_hora(data_str: str, hora_str: str) -> Optional[datetime]:
    partes = data_str.split('/')
    if len(partes) != 3:
        return None
    
    p1, p2, p3 = int(partes[0]), int(partes[1]), int(partes[2])
    if p3 < 100:
        p3 += 2000
        
    try:
        if p1 > 12:
            return datetime(p3, p2, p1, int(hora_str.split(':')[0]), int(hora_str.split(':')[1]))
        else:
            return datetime(p3, p1, p2, int(hora_str.split(':')[0]), int(hora_str.split(':')[1]))
    except ValueError:
        try:
            return datetime(p3, p2, p1, int(hora_str.split(':')[0]), int(hora_str.split(':')[1]))
        except ValueError:
            return None

def extrair_veiculo(texto: str):
    texto_lower = texto.lower()
    tipo = None
    cor = None
    
    if "moto" in texto_lower:
        tipo = "Moto"
    elif "gol" in texto_lower or "carro" in texto_lower or "palio" in texto_lower or "corsa" in texto_lower:
        tipo = "Carro"
    elif "viatura" in texto_lower:
        tipo = "Viatura"

    cores = ["preto", "preta", "branco", "branca", "cinza", "prata", "laranja", "vermelho", "vermelha", "azul"]
    for c in cores:
        if c in texto_lower:
            cor = c.capitalize()
            break
            
    return tipo, cor

def identificar_seguranca(remetente: str, texto: str) -> Optional[str]:
    rem = remetente.strip()
    
    # Ignora imediatamente portaria ou contatos administrativos
    for ign in REMETENTES_IGNORADOS:
        if ign in rem:
            return None

    # 1. Prioridade absoluta por contato/número da equipe oficial
    if rem in MAPA_CONTATOS:
        return MAPA_CONTATOS[rem]
    for tel, nome in MAPA_CONTATOS.items():
        if tel in rem:
            return nome

    # 2. Se for outro número desconhecido que não seja portaria
    texto_lower = texto.lower()
    if "carlos oliveira" in texto_lower and "marcos silva" in texto_lower:
        return "Carlos Oliveira"
    elif "carlos oliveira" in texto_lower:
        return "Carlos Oliveira"
    elif "marcos silva" in texto_lower:
        return "Marcos Silva"
    elif "alexandre santos" in texto_lower or "alexandre santos" in rem.lower():
        return "Alexandre Santos"
    elif "eduardo lima" in texto_lower or "eduardo lima" in texto_lower:
        return "Eduardo Lima"
    elif "lucas ferreira" in texto_lower:
        return "Lucas Ferreira"
        
    return None

def processar_chat_whatsapp(conteudo_texto: str, data_minima: Optional[str] = "2026-06-01") -> List[Dict[str, Any]]:
    linhas = conteudo_texto.splitlines()
    mensagens_chat = []
    dt_min = datetime.strptime(data_minima, "%Y-%m-%d") if data_minima else None

    for linha in linhas:
        linha = linha.strip()
        if not linha:
            continue
            
        m = MSG_PATTERN.match(linha)
        if not m:
            continue
            
        data_str, hora_str, remetente, mensagem = m.groups()
        dt = parse_data_hora(data_str, hora_str)
        if not dt:
            continue
            
        if dt_min and dt < dt_min:
            continue

        rem_limpo = remetente.strip()
        seguranca = identificar_seguranca(rem_limpo, mensagem)
        if not seguranca:
            continue

        msg_lower = mensagem.lower()
        tipo_evento = None
        
        if (
            "iniciando" in msg_lower or
            "reiniciando" in msg_lower or
            "início de trabalho" in msg_lower or
            "inicio de trabalho" in msg_lower
        ):
            tipo_evento = "INICIO"
            
        elif (
            "encerrando" in msg_lower or
            "encerrado" in msg_lower or
            "encerramento" in msg_lower
        ):
            tipo_evento = "FIM"
            
        v_tipo, v_cor = extrair_veiculo(mensagem)
        
        mensagens_chat.append({
            "datetime": dt,
            "remetente": rem_limpo,
            "seguranca": seguranca,
            "mensagem": mensagem,
            "tipo_evento": tipo_evento,
            "veiculo_tipo": v_tipo,
            "veiculo_cor": v_cor
        })

    turnos_finais = []
    
    msgs_por_seg = {}
    for m in mensagens_chat:
        msgs_por_seg.setdefault(m["seguranca"], []).append(m)

    for seg, msgs in msgs_por_seg.items():
        # Para Alexandre Santos, Carlos Oliveira e Lucas Ferreira (rondas contínuas por fotos/relatos)
        if seg in ["Alexandre Santos", "Carlos Oliveira", "Lucas Ferreira"]:
            blocos = []
            bloco_atual = []
            
            for m in msgs:
                if not bloco_atual:
                    bloco_atual.append(m)
                else:
                    diff_horas = (m["datetime"] - bloco_atual[-1]["datetime"]).total_seconds() / 3600
                    if m["tipo_evento"] == "INICIO" and bloco_atual:
                        blocos.append(bloco_atual)
                        bloco_atual = [m]
                    elif diff_horas <= 4.0:
                        bloco_atual.append(m)
                        if m["tipo_evento"] == "FIM":
                            blocos.append(bloco_atual)
                            bloco_atual = []
                    else:
                        blocos.append(bloco_atual)
                        bloco_atual = [m]
            if bloco_atual:
                blocos.append(bloco_atual)
                
            for b in blocos:
                dt_ini = b[0]["datetime"]
                dt_fim = b[-1]["datetime"]
                diff = dt_fim - dt_ini
                horas = round(diff.total_seconds() / 3600, 2)
                
                if horas == 0:
                    horas = 0.5
                    
                v_t, v_c = None, None
                for it in b:
                    t, c = extrair_veiculo(it["mensagem"])
                    if t and not v_t: v_t = t
                    if c and not v_c: v_c = c
                    
                if seg == "Alexandre Santos" and not v_t:
                    v_t = "Moto"
                    
                status = "Concluído"
                if any(it.get("tipo_evento") == "FIM" for it in b):
                    status = "Concluído"
                else:
                    status = "Ronda por registro fotográfico"
                    
                turnos_finais.append({
                    "seguranca": seg,
                    "telefone_origem": b[0]["remetente"],
                    "veiculo_tipo": v_t,
                    "veiculo_cor": v_c,
                    "data_inicio": dt_ini.strftime("%Y-%m-%d %H:%M"),
                    "data_fim": dt_fim.strftime("%Y-%m-%d %H:%M"),
                    "horas_trabalhadas": horas,
                    "status": status,
                    "detalhes": f"{len(b)} fotos/registros de ronda no período"
                })
            continue

        # Para quem declara INICIO / FIM / PARCIAL formalmente (Marcos Silva, Eduardo Lima)
        turno_aberto = None
        ultima_msg_ativa = None
        
        for item in msgs:
            tipo = item["tipo_evento"]
            
            if tipo == "INICIO":
                if turno_aberto:
                    fim_dt = ultima_msg_ativa["datetime"] if ultima_msg_ativa and ultima_msg_ativa["datetime"] > turno_aberto["datetime"] else None
                    horas = round((fim_dt - turno_aberto["datetime"]).total_seconds() / 3600, 2) if fim_dt else None
                    status = "Finalizado por última atividade" if horas and 0 <= horas <= 24 else "Sem encerramento"
                    
                    turnos_finais.append({
                        "seguranca": seg,
                        "telefone_origem": turno_aberto["remetente"],
                        "veiculo_tipo": turno_aberto["veiculo_tipo"],
                        "veiculo_cor": turno_aberto["veiculo_cor"],
                        "data_inicio": turno_aberto["datetime"].strftime("%Y-%m-%d %H:%M"),
                        "data_fim": fim_dt.strftime("%Y-%m-%d %H:%M") if fim_dt else None,
                        "horas_trabalhadas": horas if horas and 0 <= horas <= 24 else None,
                        "status": status,
                        "detalhes": f"Início: {turno_aberto['mensagem']}"
                    })
                
                turno_aberto = item
                ultima_msg_ativa = item

            elif tipo == "FIM":
                if turno_aberto:
                    diff = item["datetime"] - turno_aberto["datetime"]
                    horas = round(diff.total_seconds() / 3600, 2)
                    
                    msg_fim_lower = item["mensagem"].lower()
                    status = "Concluído"
                    if "parcial" in msg_fim_lower:
                        status = "Encerrado Parcial"
                        
                    turnos_finais.append({
                        "seguranca": seg,
                        "telefone_origem": turno_aberto["remetente"],
                        "veiculo_tipo": turno_aberto["veiculo_tipo"] or item["veiculo_tipo"],
                        "veiculo_cor": turno_aberto["veiculo_cor"] or item["veiculo_cor"],
                        "data_inicio": turno_aberto["datetime"].strftime("%Y-%m-%d %H:%M"),
                        "data_fim": item["datetime"].strftime("%Y-%m-%d %H:%M"),
                        "horas_trabalhadas": horas if 0 <= horas <= 24 else None,
                        "status": status,
                        "detalhes": f"Início: {turno_aberto['mensagem']} | Fim: {item['mensagem']}"
                    })
                    turno_aberto = None
                    ultima_msg_ativa = None
                else:
                    turnos_finais.append({
                        "seguranca": seg,
                        "telefone_origem": item["remetente"],
                        "veiculo_tipo": item["veiculo_tipo"],
                        "veiculo_cor": item["veiculo_cor"],
                        "data_inicio": item["datetime"].strftime("%Y-%m-%d %H:%M"),
                        "data_fim": item["datetime"].strftime("%Y-%m-%d %H:%M"),
                        "horas_trabalhadas": None,
                        "status": "Apenas encerramento registrado",
                        "detalhes": item["mensagem"]
                    })
            else:
                ultima_msg_ativa = item

        if turno_aberto:
            fim_dt = ultima_msg_ativa["datetime"] if ultima_msg_ativa and ultima_msg_ativa["datetime"] > turno_aberto["datetime"] else None
            horas = round((fim_dt - turno_aberto["datetime"]).total_seconds() / 3600, 2) if fim_dt else None
            status = "Finalizado por última atividade" if horas and 0 <= horas <= 24 else "Em aberto"
            
            turnos_finais.append({
                "seguranca": seg,
                "telefone_origem": turno_aberto["remetente"],
                "veiculo_tipo": turno_aberto["veiculo_tipo"],
                "veiculo_cor": turno_aberto["veiculo_cor"],
                "data_inicio": turno_aberto["datetime"].strftime("%Y-%m-%d %H:%M"),
                "data_fim": fim_dt.strftime("%Y-%m-%d %H:%M") if fim_dt else None,
                "horas_trabalhadas": horas if horas and 0 <= horas <= 24 else None,
                "status": status,
                "detalhes": f"Início: {turno_aberto['mensagem']}"
            })

    turnos_finais.sort(key=lambda x: x["data_inicio"], reverse=True)
    return turnos_finais
