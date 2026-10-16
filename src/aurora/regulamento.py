"""Consulta ao regulamento: devolve só trechos de UM capítulo, o do assunto perguntado.

Parte da Garantia 4. O texto completo nunca vai para instrução de agente nem para a
sessão: a busca escolhe o capítulo mais aderente e devolve apenas os artigos dele
que mais respondem à pergunta.
"""

import re
import unicodedata
from functools import lru_cache

from .config import DADOS

MAX_ARTIGOS = 3

PALAVRAS_VAZIAS = set(
    "a o as os de da do das dos e em no na nos nas um uma uns umas para por com sem que qual quais "
    "como quando onde ate sobre ao aos pode posso podem e ser sao esta estao meu minha regra regras "
    "regulamento condominio funciona horario horarios".split()
)


def _normalizar(texto):
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.lower()


def _termos(texto):
    termos = set()
    for palavra in re.findall(r"[a-z0-9]+", _normalizar(texto)):
        if len(palavra) < 3 or palavra in PALAVRAS_VAZIAS:
            continue
        termos.add(palavra[:6])  # radical grosseiro: domingos/domingo, festas/festa
    return termos


@lru_cache(maxsize=1)
def _capitulos():
    texto = (DADOS / "regulamento.md").read_text(encoding="utf-8")
    capitulos = []
    for bloco in re.split(r"(?m)^## ", texto)[1:]:
        titulo, _, corpo = bloco.partition("\n")
        artigos = [a.strip() for a in re.split(r"(?m)^(?=\*\*Art\. )", corpo) if a.strip()]
        capitulos.append(
            {
                "titulo": titulo.strip(),
                "termos_titulo": _termos(titulo),
                "artigos": [(a, _termos(a)) for a in artigos],
            }
        )
    return capitulos


def buscar(pergunta):
    termos = _termos(pergunta)
    if not termos:
        return None

    def nota_capitulo(cap):
        no_titulo = len(termos & cap["termos_titulo"])
        no_corpo = sum(len(termos & t) for _, t in cap["artigos"])
        return no_titulo * 10 + no_corpo

    melhor = max(_capitulos(), key=nota_capitulo)
    if nota_capitulo(melhor) == 0:
        return None
    artigos = sorted(melhor["artigos"], key=lambda a: len(termos & a[1]), reverse=True)
    escolhidos = [texto for texto, t in artigos[:MAX_ARTIGOS] if termos & t] or [artigos[0][0]]
    return {"capitulo": melhor["titulo"], "trechos": escolhidos}
