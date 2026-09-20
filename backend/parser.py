import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

MSG_PATTERN = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}),?\s+(\d{1,2}:\d{2})\s*-\s*([^:]+):\s*(.*)$"
)

import os
import json

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "contacts.json")
EXAMPLE_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "contacts.example.json")

def carregar_configuracao_contatos():
    target_path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else EXAMPLE_CONFIG_PATH
    guards = {}
    ignored_senders = set()
    photo_patrol_guards = {"Alexandre Santos", "Carlos Oliveira", "Lucas Ferreira"}

    if os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                guards = cfg.get("guards", {})
                ignored_senders = set(cfg.get("ignored_senders", []))
                if "photo_patrol_guards" in cfg:
                    photo_patrol_guards = set(cfg["photo_patrol_guards"])
                return guards, ignored_senders, photo_patrol_guards
        except Exception as e:
            print(f"Aviso ao carregar {target_path}: {e}")
            
    # Mapeamento fallback padrão caso os arquivos não existam
    padrao_guards = {
        "+55 11 99999-0001": "Marcos Silva",
        "Marcos Silva": "Marcos Silva",
        "+55 11 99999-0002": "Carlos Oliveira",
        "Carlos Oliveira": "Carlos Oliveira",
        "+55 11 99999-0003": "Alexandre Santos",
        "+55 11 999990001": "Alexandre Santos",
        "Alexandre Santos": "Alexandre Santos",
        "+55 15 99999-0004": "Lucas Ferreira",
        "Lucas Ferreira": "Lucas Ferreira",
        "Eduardo Lima": "Eduardo Lima"
    }
    padrao_ignorados = {"Servicos Gerais - Terceirizado", "+55 11 99999-0005", "Administracao"}
    return padrao_guards, padrao_ignorados, photo_patrol_guards

MAPA_CONTATOS, REMETENTES_IGNORADOS, RONDAS_FOTOGRAFICAS_GUARDS = carregar_configuracao_contatos()

# Regex para extrair horário retroativo mencionado na mensagem
# Ex: "encerrado as 16.45", "encerrando as 16.45", "encerrando 17:00", "encerrado 16h30", "encerrei as 18:00"
HORARIO_RETROATIVO_REGEX = re.compile(
    r"(?:encerr(?:ad[oa]|ando|ei|amento)|sa[ií]da)\s+(?:[aà]s\s+)?(\d{1,2})[:\.hH](\d{2})?",
    re.IGNORECASE
)

def detectar_formato_data(linhas: List[str], max_linhas: int = 2500) -> str:
    """Analisa as primeiras linhas para determinar se o chat usa DD/MM/AAAA ou MM/DD/AAAA."""
    dmy_count = 0
    mdy_count = 0
    for linha in linhas[:max_linhas]:
        m = re.match(r"^(\d{1,2})/(\d{1,2})/\d{2,4}", linha.strip())
        if m:
            p1, p2 = int(m.group(1)), int(m.group(2))
            if p1 > 12 and p2 <= 12:
                dmy_count += 1
            elif p2 > 12 and p1 <= 12:
                mdy_count += 1
    return "MDY" if mdy_count > dmy_count else "DMY"

def parse_data_hora(data_str: str, hora_str: str, formato_padrao: str = "DMY") -> Optional[datetime]:
    partes = data_str.split('/')
    if len(partes) != 3:
        return None
    
    try:
        p1, p2, p3 = int(partes[0]), int(partes[1]), int(partes[2])
    except ValueError:
        return None

    if p3 < 100:
        p3 += 2000

    hora_partes = hora_str.split(':')
    if len(hora_partes) < 2:
        return None
    try:
        hh, mm = int(hora_partes[0]), int(hora_partes[1])
    except ValueError:
        return None
        
    try:
        if p1 > 12:
            # Claramente Dia/Mês/Ano
            return datetime(p3, p2, p1, hh, mm)
        elif p2 > 12:
            # Claramente Mês/Dia/Ano
            return datetime(p3, p1, p2, hh, mm)
        else:
            # Ambíguo (ambos <= 12) -> usa o formato detectado no chat
            if formato_padrao == "MDY":
                return datetime(p3, p1, p2, hh, mm)
            else:
                return datetime(p3, p2, p1, hh, mm)
    except ValueError:
        try:
            return datetime(p3, p1, p2, hh, mm) if formato_padrao == "DMY" else datetime(p3, p2, p1, hh, mm)
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

def identificar_seguranca(remetente: str, mapa_contatos: Optional[Dict[str, str]] = None) -> Optional[str]:
    rem = remetente.strip()
    mapa = mapa_contatos if mapa_contatos is not None else MAPA_CONTATOS
    
    for ign in REMETENTES_IGNORADOS:
        if ign in rem:
            return None

    if rem in mapa:
        return mapa[rem]
    if rem in mapa.values():
        return rem
    for tel, nome in mapa.items():
        if tel in rem or nome in rem:
            return nome
        
    return None

def auto_descobrir_guardas(mensagens_brutas: List[Dict[str, Any]], mapa_existente: Dict[str, str]) -> Dict[str, str]:
    """Descobre nomes de seguranças a partir das mensagens de início de serviço e números de telefone."""
    mapa_descoberto = dict(mapa_existente)
    palavras_ignorar = {
        'de', 'com', 'em', 'da', 'do', 'na', 'no', 'portaria', 'moto', 'carro', 'viatura',
        'parcial', 'almoço', 'serviço', 'servicos', 'serviços', 'trabalho', 'retornando'
    }

    for mb in mensagens_brutas:
        rem = mb["remetente"].strip()
        if any(ign in rem for ign in REMETENTES_IGNORADOS):
            continue

        # Se já estiver mapeado no config com um nome de confiança, não sobrescreve
        if rem in mapa_descoberto and not re.match(r"^\+?\d[\d\s\-]+$", mapa_descoberto[rem]):
            continue

        msg = mb["mensagem"]
        # Limpa anotações de mídia ou anexos antes de extrair nome
        msg_limpa = re.sub(r'<[^>]+>', ' ', msg)
        msg_limpa = re.sub(r'IMG-\d+-WA\d+\.[a-zA-Z0-9]+(?:\s*\([^)]*\))?', ' ', msg_limpa).strip()

        # Nome antes de "iniciando/reiniciando/início de serviço" (ex: "Portugal iniciando o serviço", "Domingues, Iniciando serviço", "Mazinho iniciando serviço")
        m1 = re.search(r'(?:^|[,\.\n]|\b(?:dia|tarde|noite)\s+)([A-Za-zÀ-ÖØ-öø-ÿ]{3,20})[\s,]+(?:iniciando|reiniciando|in[ií]cio\s+de)\s+(?:os\s+|o\s+)?serviço', msg_limpa, re.IGNORECASE)
        if m1:
            nome = m1.group(1).strip()
            if nome.lower() not in ['bom', 'boa', 'olá', 'ola'] and nome.lower() not in palavras_ignorar:
                mapa_descoberto[rem] = nome
                continue

        # Nome após "iniciando serviço" (ex: "Iniciando serviço, Diego, carro preto", "Iniciando serviços carro branco.Eder Milton")
        m2 = re.search(r'(?:iniciando|reiniciando)\s+(?:os\s+|o\s+)?serviço[s]?[\s,\.]+(?:(?:de\s+)?(?:carro|moto|viatura)[^,\.]*[\s,\.]+)?([A-Za-zÀ-ÖØ-öø-ÿ\s]{3,25})', msg_limpa, re.IGNORECASE)
        if m2:
            cand = m2.group(1).strip()
            # Limpa palavras de veículos ou stop words que possam vir no final do match
            cand = re.split(r'\b(?:carro|moto|viatura|gol|palio|corsa|preto|preta|branco|branca|cinza|prata|laranja|vermelho|azul)\b', cand, flags=re.IGNORECASE)[0].strip(" ,.-")
            cand_first = cand.split()[0].lower() if cand else ''
            if cand_first and cand_first not in palavras_ignorar and len(cand) >= 3:
                mapa_descoberto[rem] = cand
                continue

        # Se o próprio remetente já for um nome textual e enviou início/fim de serviço
        msg_lower = msg.lower()
        if any(k in msg_lower for k in ["iniciando", "reiniciando", "encerrando", "encerrado"]):
            if not re.match(r"^\+?\d[\d\s\-]+$", rem) and len(rem) >= 3 and rem not in mapa_descoberto:
                mapa_descoberto[rem] = rem

    return mapa_descoberto

def parse_mensagens_chat(conteudo_texto: str, data_minima: Optional[str] = None) -> List[Dict[str, Any]]:
    linhas = conteudo_texto.splitlines()
    dt_min = datetime.strptime(data_minima, "%Y-%m-%d") if data_minima else None
    formato_data = detectar_formato_data(linhas)

    # 1. Agrupar mensagens preservando legendas de fotos e quebras de linha
    mensagens_brutas = []
    for linha in linhas:
        if not linha.strip():
            continue
        m = MSG_PATTERN.match(linha.strip())
        if m:
            data_str, hora_str, remetente, mensagem = m.groups()
            mensagens_brutas.append({
                "data_str": data_str,
                "hora_str": hora_str,
                "remetente": remetente.strip(),
                "mensagem": mensagem.strip()
            })
        else:
            # É a legenda da foto ou continuação da mensagem anterior!
            if mensagens_brutas:
                mensagens_brutas[-1]["mensagem"] += " " + linha.strip()

    # Auto-descoberta dinâmica de guardas para chats reais
    mapa_contatos_ativo = auto_descobrir_guardas(mensagens_brutas, MAPA_CONTATOS)

    mensagens_chat = []
    for mb in mensagens_brutas:
        dt = parse_data_hora(mb["data_str"], mb["hora_str"], formato_padrao=formato_data)
        if not dt:
            continue
            
        if dt_min and dt < dt_min:
            continue

        rem_limpo = mb["remetente"]
        seguranca = identificar_seguranca(rem_limpo, mapa_contatos_ativo)
        if not seguranca:
            continue

        mensagem = mb["mensagem"]
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
    return mensagens_chat

def extrair_mensagens_chat(conteudo_texto: str, data_minima: Optional[str] = None) -> List[Dict[str, Any]]:
    """Extrai e enriquece mensagens do chat com metadados de segurança e evento (alias para parse_mensagens_chat)."""
    return parse_mensagens_chat(conteudo_texto, data_minima)

def processar_chat_whatsapp(conteudo_texto: str, data_minima: Optional[str] = None) -> List[Dict[str, Any]]:
    mensagens_chat = parse_mensagens_chat(conteudo_texto, data_minima)

    turnos_finais = []
    msgs_por_seg = {}
    for m in mensagens_chat:
        msgs_por_seg.setdefault(m["seguranca"], []).append(m)

    for seg, msgs in msgs_por_seg.items():
        # Para rondas contínuas por fotos/relatos configuradas em contacts.json
        if seg in RONDAS_FOTOGRAFICAS_GUARDS:
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
        msgs_do_turno_atual = []
        
        for item in msgs:
            tipo = item["tipo_evento"]
            
            if tipo == "INICIO":
                # Se já tinha um turno aberto que não teve FIM formal:
                if turno_aberto:
                    # Busca a última atividade válida daquele dia
                    dt_ini = turno_aberto["datetime"]
                    
                    # Mensagens enviadas no mesmo dia do início ou até a manhã seguinte (< 16 horas)
                    msgs_mesmo_turno = [m for m in msgs_do_turno_atual if m["datetime"] > dt_ini and (m["datetime"] - dt_ini).total_seconds() / 3600 <= 16.0]
                    
                    if msgs_mesmo_turno:
                        ultima_msg = msgs_mesmo_turno[-1]
                        dt_fim = ultima_msg["datetime"]
                        
                        # Verifica se na mensagem havia horário retroativo (ex: "encerrado as 16:45")
                        m_ret = HORARIO_RETROATIVO_REGEX.search(ultima_msg["mensagem"])
                        if m_ret:
                            hr_h = int(m_ret.group(1))
                            hr_m = int(m_ret.group(2)) if m_ret.group(2) else 0
                            try:
                                dt_fim = dt_fim.replace(hour=hr_h, minute=hr_m)
                            except Exception:
                                pass
                                
                        diff = dt_fim - dt_ini
                        horas = round(diff.total_seconds() / 3600, 2)
                        status = "Finalizado por última atividade" if 0 <= horas <= 16 else "Sem encerramento"
                        
                        turnos_finais.append({
                            "seguranca": seg,
                            "telefone_origem": turno_aberto["remetente"],
                            "veiculo_tipo": turno_aberto["veiculo_tipo"],
                            "veiculo_cor": turno_aberto["veiculo_cor"],
                            "data_inicio": dt_ini.strftime("%Y-%m-%d %H:%M"),
                            "data_fim": dt_fim.strftime("%Y-%m-%d %H:%M"),
                            "horas_trabalhadas": horas if 0 <= horas <= 16 else None,
                            "status": status,
                            "detalhes": f"Início: {turno_aberto['mensagem']} | Fim estimado: {ultima_msg['mensagem']}"
                        })
                    else:
                        turnos_finais.append({
                            "seguranca": seg,
                            "telefone_origem": turno_aberto["remetente"],
                            "veiculo_tipo": turno_aberto["veiculo_tipo"],
                            "veiculo_cor": turno_aberto["veiculo_cor"],
                            "data_inicio": dt_ini.strftime("%Y-%m-%d %H:%M"),
                            "data_fim": None,
                            "horas_trabalhadas": None,
                            "status": "Sem encerramento",
                            "detalhes": f"Início: {turno_aberto['mensagem']}"
                        })
                
                turno_aberto = item
                msgs_do_turno_atual = [item]

            elif tipo == "FIM":
                if turno_aberto:
                    dt_ini = turno_aberto["datetime"]
                    dt_fim = item["datetime"]
                    
                    # Verifica se no texto do fim tem horário retroativo especificado
                    m_ret = HORARIO_RETROATIVO_REGEX.search(item["mensagem"])
                    if m_ret:
                        hr_h = int(m_ret.group(1))
                        hr_m = int(m_ret.group(2)) if m_ret.group(2) else 0
                        try:
                            dt_fim = dt_fim.replace(hour=hr_h, minute=hr_m)
                        except Exception:
                            pass
                            
                    diff = dt_fim - dt_ini
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
                        "data_inicio": dt_ini.strftime("%Y-%m-%d %H:%M"),
                        "data_fim": dt_fim.strftime("%Y-%m-%d %H:%M"),
                        "horas_trabalhadas": horas if 0 <= horas <= 24 else None,
                        "status": status,
                        "detalhes": f"Início: {turno_aberto['mensagem']} | Fim: {item['mensagem']}"
                    })
                    turno_aberto = None
                    msgs_do_turno_atual = []
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
                # Mensagem intermediária durante o turno
                msgs_do_turno_atual.append(item)

        if turno_aberto:
            dt_ini = turno_aberto["datetime"]
            msgs_mesmo_turno = [m for m in msgs_do_turno_atual if m["datetime"] > dt_ini and (m["datetime"] - dt_ini).total_seconds() / 3600 <= 16.0]
            if msgs_mesmo_turno:
                ultima_msg = msgs_mesmo_turno[-1]
                dt_fim = ultima_msg["datetime"]
                diff = dt_fim - dt_ini
                horas = round(diff.total_seconds() / 3600, 2)
                status = "Finalizado por última atividade" if 0 <= horas <= 16 else "Em aberto"
                
                turnos_finais.append({
                    "seguranca": seg,
                    "telefone_origem": turno_aberto["remetente"],
                    "veiculo_tipo": turno_aberto["veiculo_tipo"],
                    "veiculo_cor": turno_aberto["veiculo_cor"],
                    "data_inicio": dt_ini.strftime("%Y-%m-%d %H:%M"),
                    "data_fim": dt_fim.strftime("%Y-%m-%d %H:%M"),
                    "horas_trabalhadas": horas if 0 <= horas <= 16 else None,
                    "status": status,
                    "detalhes": f"Início: {turno_aberto['mensagem']} | Fim estimado: {ultima_msg['mensagem']}"
                })
            else:
                turnos_finais.append({
                    "seguranca": seg,
                    "telefone_origem": turno_aberto["remetente"],
                    "veiculo_tipo": turno_aberto["veiculo_tipo"],
                    "veiculo_cor": turno_aberto["veiculo_cor"],
                    "data_inicio": dt_ini.strftime("%Y-%m-%d %H:%M"),
                    "data_fim": None,
                    "horas_trabalhadas": None,
                    "status": "Em aberto",
                    "detalhes": f"Início: {turno_aberto['mensagem']}"
                })

    turnos_finais.sort(key=lambda x: x["data_inicio"], reverse=True)
    return turnos_finais
