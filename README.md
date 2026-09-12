# Ronda Segurança - Auditoria de Horas & Turnos

Sistema desacoplado em **FastAPI** + **SQLite** com interface web moderna para ingestão, auditoria e exportação em Excel das horas trabalhadas pelos seguranças a partir do histórico exportado do WhatsApp.

## 🚀 Tecnologias
- **Backend:** FastAPI (Python 3.10+)
- **Banco de Dados:** SQLite3 nativo
- **Frontend:** HTML5, Tailwind CSS (via CDN) e Vanilla JavaScript
- **Exportação:** Pandas / OpenPyXL (.xlsx)
- **DevOps:** Dockerfile e docker-compose.yml inclusos

---

## 📦 Como rodar localmente

### 1. Criar ambiente virtual e instalar dependências
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Iniciar o servidor FastAPI
```bash
uvicorn backend.main:app --reload --port 8000
```

Abra no navegador: [http://localhost:8000](http://localhost:8000)

---

## 🐳 Como rodar com Docker

```bash
docker compose up --build -d
```

O banco SQLite persistirá na pasta `./data/rondas.db`.

---

## ⚙️ Funcionalidades
1. **Upload do `.txt` do WhatsApp:** Processamento instantâneo de milhares de linhas sem gastar tokens.
2. **Cálculo automático de intervalos:** Casamento de início e fim de serviço, identificando veículo e cor.
3. **Resumo por segurança:** Total de horas por segurança e média de horas por turno.
4. **Exportação:** Download direto para planilha Excel (`.xlsx`) com filtros aplicados.
