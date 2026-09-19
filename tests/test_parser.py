from datetime import datetime
from backend.parser import processar_chat_whatsapp, HORARIO_RETROATIVO_REGEX, extrair_veiculo

def test_retroactive_hour_regex():
    cases = [
        ("Encerrando as 16.45", (16, 45)),
        ("encerrado as 17:00", (17, 0)),
        ("encerrei as 18:30", (18, 30)),
        ("saida as 19h", (19, 0)),
        ("saída às 20:15", (20, 15)),
    ]
    for text, expected in cases:
        m = HORARIO_RETROATIVO_REGEX.search(text)
        assert m is not None, f"Failed on: {text}"
        h = int(m.group(1))
        min_val = int(m.group(2)) if m.group(2) else 0
        assert (h, min_val) == expected

def test_vehicle_extraction():
    tipo, cor = extrair_veiculo("Iniciando com moto laranja na portaria")
    assert tipo == "Moto"
    assert cor == "Laranja"

    tipo, cor = extrair_veiculo("Viatura carro preto em ronda")
    assert tipo == "Carro"
    assert cor == "Preto"

def test_processar_chat_synthetic():
    sample = """8/20/26, 06:00 - Alexandre Santos: Iniciando serviço, Alexandre Santos, moto laranja
8/20/26, 09:00 - Alexandre Santos: Ronda no setor norte ok
8/20/26, 12:00 - Alexandre Santos: Encerrando serviços
8/20/26, 13:00 - Servicos Gerais - Terceirizado: Início de trabalho Servicos Gerais
8/20/26, 18:00 - Carlos Oliveira: Iniciando serviço, Carlos Oliveira carro preto
8/20/26, 22:00 - Carlos Oliveira: Encerrando serviços
"""
    turnos = processar_chat_whatsapp(sample, data_minima="2026-08-01")
    assert len(turnos) == 2
    # Alexandre Santos: 6h to 12h = 6h
    # Carlos Oliveira: 18h to 22h = 4h
    segurancas = {t["seguranca"] for t in turnos}
    assert "Alexandre Santos" in segurancas
    assert "Carlos Oliveira" in segurancas
    assert "Servicos Gerais" not in segurancas
