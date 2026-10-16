"""Volta reservas e visitantes ao estado de `dados/`. As sessões continuam."""

from . import dados


def main():
    dados.restaurar()
    print("Dados restaurados a partir de dados/ (reservas e visitantes). Sessões mantidas.")
