import re
from datetime import datetime
from typing import List, Dict, Any, Optional

# Regex padrao WhatsApp:
# Ex: "1/19/24, 18:06 - Alexandre Santos: Iniciando serviço, Alexandre Santos, moto laranja"
# Formatos de data comuns: M/D/YY ou DD/MM/YYYY
MSG_PATTERN = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}),?\s+(\d{1,2}:\d{2})\s*-\s*([^:]+):\s*(.*)$"
)

# Mapa fixo por numero/remetente identificado no grupo
MAPA_REMETENTES = {
    "+55 11 99999-0001": "Marcos Silva",
    "+55 11 99999-0002": "Carlos Oliveira",
    "+55 15 99999-0004": "Lucas Ferreira",
    "+55 11 99999-0005": "Apoio Operacional",
    "Alexandre Santos": "Alexandre Santos",
    "Eduardo Lima": "Eduardo Lima",
    "Eduardo Lima": "Eduardo Lima"
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
    elif "gol" in texto_lower or "carro" in texto_lower or "palio" in texto_lower:
        tipo = "Carro"
    elif "viatura" in texto_lower:
        tipo = "Viatura"

    cores = ["preto", "preta", "branco", "branca", "cinza", "prata", "laranja", "vermelho", "vermelha", "azul"]
    for c in cores:
        if c in texto_lower:
            cor = c.capitalize()
            break
            
    return tipo, cor

def normalizar_seguranca(remetente: str, texto: str) -> str:
    rem = remetente.strip()
    texto_lower = texto.lower()
    
    # 1. Checa se o remetente ja tem apelido cadastrado
    if rem in MAPA_REMETENTES:
        return MAPA_REMETENTES[rem]

    # 2. Se houver nome no texto
    nomes = [
        ("marcos silva", "Marcos Silva"),
        ("eduardo lima", "Eduardo Lima"),
        ("eduardo lima", "Eduardo Lima"),
        ("alexandre santos", "Alexandre Santos"),
        ("carlos oliveira", "Carlos Oliveira"),
        ("lucas ferreira", "Lucas Ferreira"),
        ("apoio operacional", "Apoio Operacional"),
        ("apoio", "Apoio Operacional"),
        ("santos", "Santos")
    ]
    for chave, nome_padrao in nomes:
        if chave in texto_lower or chave in rem.lower():
            return nome_padrao
            
    return rem

def processar_chat_whatsapp(conteudo_texto: str, data_minima: Optional[str] = "2026-06-01") -> List[Dict[str, Any]]:
    linhas = conteudo_texto.splitlines()
    
    # 1. Parse de todas as mensagens do chat
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
            
        # Filtro de data minima se configurado
        if dt_min and dt < dt_min:
            continue

        msg_lower = mensagem.lower()
        tipo_evento = None
        if (
            "iniciando servi" in msg_lower or 
            "reiniciando servi" in msg_lower or 
            "iniciando o servi" in msg_lower or 
            "iniciando o serviço" in msg_lower or
            "iniciando." in msg_lower or
            "iniciando" in msg_lower
        ):
            tipo_evento = "INICIO"
        elif (
            "encerrando servi" in msg_lower or 
            "encerrado o servi" in msg_lower or 
            "encerramento  de servi" in msg_lower or
            "encerramento de servi" in msg_lower or
            "encerrando parcial" in msg_lower or
            "encerrando." in msg_lower or
            "encerrando" in msg_lower
        ):
            tipo_evento = "FIM"
            
        seguranca = normalizar_seguranca(remetente, mensagem)
        v_tipo, v_cor = extrair_veiculo(mensagem)
        
        mensagens_chat.append({
            "datetime": dt,
            "remetente": remetente.strip(),
            "seguranca": seguranca,
            "mensagem": mensagem,
            "tipo_evento": tipo_evento,
            "veiculo_tipo": v_tipo,
            "veiculo_cor": v_cor
        })

    # 2. Casamento de turnos
    turnos_finais = []
    abertos: Dict[str, Dict[str, Any]] = {}
    ultima_msg_por_seguranca: Dict[str, Dict[str, Any]] = {}

    for item in mensagens_chat:
        seg = item["seguranca"]
        tipo = item["tipo_evento"]
        
        if tipo == "INICIO":
            # Se ja havia um turno aberto deste seguranca sem "FIM", fechamos com a ultima mensagem antes desse novo inicio
            if seg in abertos:
                turno_antigo = abertos[seg]
                ultima_msg = ultima_msg_por_seguranca.get(seg)
                
                if ultima_msg and ultima_msg["datetime"] > turno_antigo["datetime"]:
                    dt_fim = ultima_msg["datetime"]
                    diff = dt_fim - turno_antigo["datetime"]
                    horas = round(diff.total_seconds() / 3600, 2)
                    status = "Finalizado por última atividade" if 0 <= horas <= 24 else "Atenção: Horário inconsistente"
                    
                    turnos_finais.append({
                        "seguranca": seg,
                        "telefone_origem": turno_antigo["remetente"],
                        "veiculo_tipo": turno_antigo["veiculo_tipo"],
                        "veiculo_cor": turno_antigo["veiculo_cor"],
                        "data_inicio": turno_antigo["datetime"].strftime("%Y-%m-%d %H:%M"),
                        "data_fim": dt_fim.strftime("%Y-%m-%d %H:%M"),
                        "horas_trabalhadas": horas if 0 <= horas <= 24 else None,
                        "status": status,
                        "detalhes": f"Início: {turno_antigo['mensagem']} | Fim estimado (última msg): {ultima_msg['mensagem']}"
                    })
                else:
                    turnos_finais.append({
                        "seguranca": seg,
                        "telefone_origem": turno_antigo["remetente"],
                        "veiculo_tipo": turno_antigo["veiculo_tipo"],
                        "veiculo_cor": turno_antigo["veiculo_cor"],
                        "data_inicio": turno_antigo["datetime"].strftime("%Y-%m-%d %H:%M"),
                        "data_fim": None,
                        "horas_trabalhadas": None,
                        "status": "Sem encerramento",
                        "detalhes": turno_antigo["mensagem"]
                    })

            abertos[seg] = item
            ultima_msg_por_seguranca[seg] = item

        elif tipo == "FIM":
            if seg in abertos:
                turno_inicio = abertos.pop(seg)
                diff = item["datetime"] - turno_inicio["datetime"]
                horas = round(diff.total_seconds() / 3600, 2)
                
                status = "Concluído"
                if horas < 0 or horas > 24:
                    status = "Atenção: Horário inconsistente"
                    
                turnos_finais.append({
                    "seguranca": seg,
                    "telefone_origem": turno_inicio["remetente"],
                    "veiculo_tipo": turno_inicio["veiculo_tipo"],
                    "veiculo_cor": turno_inicio["veiculo_cor"],
                    "data_inicio": turno_inicio["datetime"].strftime("%Y-%m-%d %H:%M"),
                    "data_fim": item["datetime"].strftime("%Y-%m-%d %H:%M"),
                    "horas_trabalhadas": horas if 0 <= horas <= 24 else None,
                    "status": status,
                    "detalhes": f"Início: {turno_inicio['mensagem']} | Fim: {item['mensagem']}"
                })
            else:
                # Encerramento avulso (ex: iniciou no dia anterior ao filtro ou mensagem inicial perdida)
                # Tenta pegar a primeira mensagem do dia desse seguranca se existir
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
            ultima_msg_por_seguranca[seg] = item
        else:
            # Mensagem durante o servico (localizacao, aviso de viatura, etc)
            ultima_msg_por_seguranca[seg] = item

    # Restantes em aberto no final do arquivo
    for seg, turno in abertos.items():
        ultima_msg = ultima_msg_por_seguranca.get(seg)
        if ultima_msg and ultima_msg["datetime"] > turno["datetime"]:
            diff = ultima_msg["datetime"] - turno["datetime"]
            horas = round(diff.total_seconds() / 3600, 2)
            turnos_finais.append({
                "seguranca": seg,
                "telefone_origem": turno["remetente"],
                "veiculo_tipo": turno["veiculo_tipo"],
                "veiculo_cor": turno["veiculo_cor"],
                "data_inicio": turno["datetime"].strftime("%Y-%m-%d %H:%M"),
                "data_fim": ultima_msg["datetime"].strftime("%Y-%m-%d %H:%M"),
                "horas_trabalhadas": horas if 0 <= horas <= 24 else None,
                "status": "Finalizado por última atividade",
                "detalhes": f"Início: {turno['mensagem']} | Fim estimado (última msg): {ultima_msg['mensagem']}"
            })
        else:
            turnos_finais.append({
                "seguranca": seg,
                "telefone_origem": turno["remetente"],
                "veiculo_tipo": turno["veiculo_tipo"],
                "veiculo_cor": turno["veiculo_cor"],
                "data_inicio": turno["datetime"].strftime("%Y-%m-%d %H:%M"),
                "data_fim": None,
                "horas_trabalhadas": None,
                "status": "Em aberto",
                "detalhes": turno["mensagem"]
            })
        
    return turnos_finais
