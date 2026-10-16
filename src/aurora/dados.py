"""Dados do condomínio em SQLite: o que vale é o que está gravado aqui, não o que o modelo lembra.

Duas garantias moram neste arquivo:
- Garantia 5: o índice único parcial `reserva_ativa_unica` impede duas reservas ativas
  para a mesma área e data no instante da gravação, sem conferência prévia.
- Garantia 1 (executar uma única vez): a retomada de uma tool confirmada é at-least-once
  no ADK, então cada gravação leva o id da chamada de tool (`chamada`) com unicidade.
"""

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date

from .config import DADOS, DB_CONDOMINIO

ESQUEMA = """
CREATE TABLE IF NOT EXISTS apartamentos (
    numero  TEXT PRIMARY KEY,
    morador TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS areas (
    id   TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    taxa REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reservas (
    codigo      TEXT PRIMARY KEY,
    apartamento TEXT NOT NULL,
    area        TEXT NOT NULL REFERENCES areas(id),
    data        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa', 'cancelada')),
    chamada     TEXT UNIQUE
);
CREATE UNIQUE INDEX IF NOT EXISTS reserva_ativa_unica
    ON reservas(area, data) WHERE status = 'ativa';
CREATE TABLE IF NOT EXISTS visitantes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    apartamento TEXT NOT NULL,
    nome        TEXT NOT NULL,
    data        TEXT NOT NULL,
    chamada     TEXT UNIQUE
);
-- Todo código já emitido, inclusive de reserva cancelada ou apagada por restauração.
CREATE TABLE IF NOT EXISTS codigos_emitidos (
    codigo TEXT PRIMARY KEY
);
"""


@contextmanager
def conexao():
    DB_CONDOMINIO.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_CONDOMINIO, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
    finally:
        con.close()


@contextmanager
def transacao():
    """Transação de escrita: BEGIN IMMEDIATE pega o lock de escrita na hora."""
    with conexao() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            yield con
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise


def _ler(nome):
    with open(DADOS / nome, encoding="utf-8") as fh:
        return json.load(fh)


def preparar():
    """Cria o banco com os dados iniciais se ele ainda não existir."""
    with conexao() as con:
        con.executescript(ESQUEMA)
        vazio = con.execute("SELECT COUNT(*) FROM apartamentos").fetchone()[0] == 0
    if vazio:
        restaurar()


def restaurar():
    """Volta reservas e visitantes ao estado de `dados/`. Os códigos já emitidos continuam reservados."""
    with conexao() as con:
        con.executescript(ESQUEMA)
    with transacao() as con:
        con.execute("DELETE FROM reservas")
        con.execute("DELETE FROM visitantes")
        con.execute("DELETE FROM areas")
        con.execute("DELETE FROM apartamentos")
        con.executemany(
            "INSERT INTO apartamentos (numero, morador) VALUES (:numero, :morador)",
            _ler("apartamentos.json"),
        )
        con.executemany(
            "INSERT INTO areas (id, nome, taxa) VALUES (:id, :nome, :taxa)",
            _ler("areas.json"),
        )
        reservas = _ler("reservas.json")
        con.executemany(
            "INSERT INTO reservas (codigo, apartamento, area, data) VALUES (:codigo, :apartamento, :area, :data)",
            reservas,
        )
        con.executemany(
            "INSERT OR IGNORE INTO codigos_emitidos (codigo) VALUES (:codigo)", reservas
        )
        con.executemany(
            "INSERT INTO visitantes (apartamento, nome, data) VALUES (:apartamento, :nome, :data)",
            _ler("visitantes.json"),
        )


# ------------------------------------------------------------------ consultas


def apartamento_existe(numero):
    with conexao() as con:
        return con.execute("SELECT 1 FROM apartamentos WHERE numero = ?", (numero,)).fetchone() is not None


def areas():
    with conexao() as con:
        return [dict(r) for r in con.execute("SELECT id, nome, taxa FROM areas ORDER BY nome")]


def area(area_id):
    with conexao() as con:
        r = con.execute("SELECT id, nome, taxa FROM areas WHERE id = ?", (area_id,)).fetchone()
        return dict(r) if r else None


def reservas_do_apartamento(apartamento):
    with conexao() as con:
        return [
            dict(r)
            for r in con.execute(
                "SELECT codigo, area, data FROM reservas"
                " WHERE apartamento = ? AND status = 'ativa' ORDER BY data, area",
                (apartamento,),
            )
        ]


def visitantes_do_apartamento(apartamento):
    with conexao() as con:
        return [
            dict(r)
            for r in con.execute(
                "SELECT nome, data FROM visitantes WHERE apartamento = ? ORDER BY data, nome",
                (apartamento,),
            )
        ]


def area_livre(area_id, data):
    """Só diz se está livre. Nunca de quem é a reserva."""
    with conexao() as con:
        return con.execute(
            "SELECT 1 FROM reservas WHERE area = ? AND data = ? AND status = 'ativa'",
            (area_id, data),
        ).fetchone() is None


def data_valida(texto):
    try:
        return date.fromisoformat(texto).isoformat() == texto
    except (TypeError, ValueError):
        return False


# ------------------------------------------------------------------ gravações


def _novo_codigo(con):
    while True:
        codigo = f"RSV-{secrets.randbelow(900000) + 100000}"
        try:
            con.execute("INSERT INTO codigos_emitidos (codigo) VALUES (?)", (codigo,))
            return codigo
        except sqlite3.IntegrityError:
            continue


def reservar(apartamento, area_id, data, chamada):
    """Grava a reserva. Devolve {'ok': True, 'codigo'} ou {'ok': False, 'motivo'}.

    A exclusividade é do índice único, no instante do INSERT. Uma segunda execução
    da mesma chamada de tool devolve a reserva já gravada em vez de duplicar.
    """
    with transacao() as con:
        if chamada:
            ja = con.execute(
                "SELECT codigo, area, data FROM reservas WHERE chamada = ?", (chamada,)
            ).fetchone()
            if ja:
                return {"ok": True, "codigo": ja["codigo"], "area": ja["area"], "data": ja["data"]}
        codigo = _novo_codigo(con)
        try:
            con.execute(
                "INSERT INTO reservas (codigo, apartamento, area, data, chamada) VALUES (?, ?, ?, ?, ?)",
                (codigo, apartamento, area_id, data, chamada),
            )
        except sqlite3.IntegrityError:
            # No SQLite o erro desfaz só este INSERT; a transação segue e o código emitido
            # fica queimado em codigos_emitidos, para nunca ser reutilizado.
            # Quem recusou foi o índice reserva_ativa_unica: a data já está ocupada.
            return {"ok": False, "motivo": "ocupada"}
    return {"ok": True, "codigo": codigo, "area": area_id, "data": data}


def cancelar(apartamento, area_id, data):
    """Cancela a reserva ativa DO PRÓPRIO apartamento naquela área e data."""
    with transacao() as con:
        cur = con.execute(
            "UPDATE reservas SET status = 'cancelada'"
            " WHERE apartamento = ? AND area = ? AND data = ? AND status = 'ativa'",
            (apartamento, area_id, data),
        )
        return cur.rowcount > 0


def autorizar_visitante(apartamento, nome, data, chamada):
    with transacao() as con:
        if chamada:
            ja = con.execute("SELECT nome, data FROM visitantes WHERE chamada = ?", (chamada,)).fetchone()
            if ja:
                return {"ok": True, "nome": ja["nome"], "data": ja["data"]}
        con.execute(
            "INSERT INTO visitantes (apartamento, nome, data, chamada) VALUES (?, ?, ?, ?)",
            (apartamento, nome, data, chamada),
        )
    return {"ok": True, "nome": nome, "data": data}
