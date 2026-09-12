import re
from datetime import datetime
from typing import List, Dict, Any, Optional

# Regex padrao WhatsApp:
# Ex: "1/19/24, 18:06 - Alexandre Santos: Iniciando serviço, Alexandre Santos, moto laranja"
# Formatos de data comuns: M/D/YY ou DD/MM/YYYY
MSG_PATTERN = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}),?\s+(\d{1,2}:\d{2})\s*-\s*([^:]+):\s*(.*)$"
)

def parse_data_hora(data_str: str, hora_str: str) -> Optional[datetime]:
    partes = data_str.split('/')
    if len(partes) != 3:
        return None
    
    p1, p2, p3 = int(partes[0]), int(partes[1]), int(partes[2])
    if p3 < 100:
        p3 += 2000
        
    # No arquivo do usuario: 1/19/24 -> Mes 1, Dia 19, Ano 2024 (formato US M/D/YY)
    # Se p1 > 12 -> formato eh D/M/Y
    try:
        if p1 > 12:
            return datetime(p3, p2, p1, int(hora_str.split(':')[0]), int(hora_str.split(':')[1]))
        else:
            return datetime(p3, p1, p2, int(hora_str.split(':')[0]), int(hora_str.split(':')[1]))
    except ValueError:
        # Fallback invertido
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
    elif "carro" in texto_lower:
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
    texto_lower = texto.lower()
    
    nomes_conhecidos = ["Alexandre Santos", "Eduardo Lima", "Eduardo Lima", "Carlos Oliveira", "Marcos Silva", "Santos"]
    for nome in nomes_conhecidos:
        if nome.lower() in texto_lower or nome.lower() in remetente.lower():
            return nome
            
    # Se nao achou nome no texto, usa o remetente limpo
    remetente_limpo = remetente.strip()
    if remetente_limpo.startswith("+"):
        return remetente_limpo
    return remetente_limpo

def processar_chat_whatsapp(conteudo_texto: str) -> List[Dict[str, Any]]:
    linhas = conteudo_texto.splitlines()
    
    eventos = []
    
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
            
        msg_lower = mensagem.lower()
        
        tipo_evento = None
        if "iniciando servi" in msg_lower or "reiniciando servi" in msg_lower or "iniciando o servi" in msg_lower:
            tipo_evento = "INICIO"
        elif "encerrando servi" in msg_lower or "encerrado o servi" in msg_lower or "encerrando parcial" in msg_lower:
            tipo_evento = "FIM"
            
        if tipo_evento:
            seguranca = normalizar_seguranca(remetente, mensagem)
            veiculo_tipo, veiculo_cor = extrair_veiculo(mensagem)
            
            eventos.append({
                "datetime": dt,
                "tipo": tipo_evento,
                "remetente": remetente.strip(),
                "seguranca": seguranca,
                "mensagem": mensagem,
                "veiculo_tipo": veiculo_tipo,
                "veiculo_cor": veiculo_cor
            })
            
    # Casamento de Inicios com Encerramentos (Shift tracking)
    # Agrupamos por seguranca
    turnos_finais = []
    abertos_por_seguranca: Dict[str, Dict[str, Any]] = {}
    
    for ev in eventos:
        seg = ev["seguranca"]
        tipo = ev["tipo"]
        
        if tipo == "INICIO":
            # Se ja tinha um aberto sem encerramento, fecha como inconcluso
            if seg in abertos_por_seguranca:
                turno_antigo = abertos_por_seguranca[seg]
                turnos_finais.append({
                    "seguranca": turno_antigo["seguranca"],
                    "telefone_origem": turno_antigo["remetente"],
                    "veiculo_tipo": turno_antigo["veiculo_tipo"],
                    "veiculo_cor": turno_antigo["veiculo_cor"],
                    "data_inicio": turno_antigo["datetime"].strftime("%Y-%m-%d %H:%M"),
                    "data_fim": None,
                    "horas_trabalhadas": None,
                    "status": "Sem encerramento",
                    "detalhes": turno_antigo["mensagem"]
                })
            
            abertos_por_seguranca[seg] = ev
            
        elif tipo == "FIM":
            if seg in abertos_por_seguranca:
                turno_inicio = abertos_por_seguranca.pop(seg)
                diff = ev["datetime"] - turno_inicio["datetime"]
                horas = round(diff.total_seconds() / 3600, 2)
                
                # Se diff for negativa ou bizarra (ex > 24h), marcar alerta
                status = "Concluído"
                if horas < 0 or horas > 24:
                    status = "Atenção: Horário inconsistente"
                    
                turnos_finais.append({
                    "seguranca": seg,
                    "telefone_origem": turno_inicio["remetente"],
                    "veiculo_tipo": turno_inicio["veiculo_tipo"],
                    "veiculo_cor": turno_inicio["veiculo_cor"],
                    "data_inicio": turno_inicio["datetime"].strftime("%Y-%m-%d %H:%M"),
                    "data_fim": ev["datetime"].strftime("%Y-%m-%d %H:%M"),
                    "horas_trabalhadas": horas if 0 <= horas <= 24 else None,
                    "status": status,
                    "detalhes": f"Início: {turno_inicio['mensagem']} | Fim: {ev['mensagem']}"
                })
            else:
                # Encerramento sem inicio registrado
                turnos_finais.append({
                    "seguranca": seg,
                    "telefone_origem": ev["remetente"],
                    "veiculo_tipo": ev["veiculo_tipo"],
                    "veiculo_cor": ev["veiculo_cor"],
                    "data_inicio": ev["datetime"].strftime("%Y-%m-%d %H:%M"),
                    "data_fim": ev["datetime"].strftime("%Y-%m-%d %H:%M"),
                    "horas_trabalhadas": None,
                    "status": "Apenas encerramento registrado",
                    "detalhes": ev["mensagem"]
                })
                
    # Restantes em aberto
    for seg, turno in abertos_por_seguranca.items():
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
