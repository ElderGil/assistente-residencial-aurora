"""Caminhos e configuração lidos do ambiente."""

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ / ".env")

DADOS = RAIZ / "dados"
VAR = RAIZ / "var"
DB_CONDOMINIO = VAR / "condominio.db"
DB_SESSOES = VAR / "sessoes.db"

MODELO_PRINCIPAL = os.environ.get("MODELO_PRINCIPAL") or "gemini-3.8-flash"
MODELO_ESPECIALISTAS = os.environ.get("MODELO_ESPECIALISTAS") or "gemini-3.8-flash"

NOME_APP = "residencial_aurora"
