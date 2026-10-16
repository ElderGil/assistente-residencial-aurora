"""API do assistente: o contrato do enunciado.

Garantia 1 (lado da API): `confirmacoes_pendentes` é calculado a partir dos eventos
gravados na sessão, e a rota de confirmações só repassa ao ADK a resposta de uma
confirmação que ainda está pendente naquela sessão. Qualquer outro id, inclusive o de
uma confirmação já respondida, recebe 409 antes de chegar ao modelo ou às tools.
O ADK sozinho aceitaria a segunda resposta e executaria a ação de novo.
"""

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from google.genai import types
from pydantic import BaseModel

from . import dados
from .ferramentas import CHAVE_APARTAMENTO
from .runtime import app as app_adk
from .runtime import criar_runner

USUARIO = "morador"
CONFIRMACAO = "adk_request_confirmation"
ACOES = {
    "reservar_area": "reservar_area_com_cobranca",
    "autorizar_visitante": "liberar_entrada_de_visitante",
}

runner = criar_runner()
travas = defaultdict(asyncio.Lock)  # uma execução por sessão de cada vez


@asynccontextmanager
async def ciclo_de_vida(_):
    dados.preparar()
    yield


api = FastAPI(title="Assistente do Residencial Aurora", lifespan=ciclo_de_vida)
app = api  # nome que o uvicorn procura


class NovaSessao(BaseModel):
    apartamento: str


class Mensagem(BaseModel):
    texto: str


class RespostaConfirmacao(BaseModel):
    id: str
    confirmado: bool


async def _sessao(session_id):
    sessao = await runner.session_service.get_session(
        app_name=app_adk.name, user_id=USUARIO, session_id=session_id
    )
    if sessao is None:
        raise HTTPException(status_code=404, detail="Sessão inexistente.")
    return sessao


def _detalhes(chamada_original):
    nome = chamada_original.get("name")
    args = dict(chamada_original.get("args") or {})
    if nome == "reservar_area":
        info = dados.area(args.get("area"))
        if info:
            args["taxa"] = info["taxa"]
    return ACOES.get(nome, nome), args


def pendencias(sessao):
    """Confirmações pedidas pelo sistema e ainda sem resposta, na ordem em que surgiram."""
    abertas = {}
    for evento in sessao.events:
        for parte in (evento.content.parts if evento.content else None) or []:
            if parte.function_call and parte.function_call.name == CONFIRMACAO:
                original = (parte.function_call.args or {}).get("originalFunctionCall") or {}
                acao, detalhes = _detalhes(original)
                abertas[parte.function_call.id] = {
                    "id": parte.function_call.id,
                    "acao": acao,
                    "detalhes": detalhes,
                }
            if (
                parte.function_response
                and parte.function_response.name == CONFIRMACAO
                and evento.author == "user"
            ):
                abertas.pop(parte.function_response.id, None)
    return list(abertas.values())


async def _executar(session_id, mensagem):
    textos = []
    async for evento in runner.run_async(user_id=USUARIO, session_id=session_id, new_message=mensagem):
        if evento.author == "user" or not evento.content or evento.partial:
            continue
        for parte in evento.content.parts or []:
            if parte.text and not parte.thought:
                textos.append(parte.text.strip())
    sessao = await _sessao(session_id)
    return {"resposta": "\n".join(t for t in textos if t), "confirmacoes_pendentes": pendencias(sessao)}


@api.post("/sessoes", status_code=201)
async def criar_sessao(corpo: NovaSessao):
    if not dados.apartamento_existe(corpo.apartamento):
        raise HTTPException(status_code=422, detail="Apartamento inexistente.")
    # Garantia 2: o apartamento entra no state uma única vez, aqui, e é dele que as tools leem.
    sessao = await runner.session_service.create_session(
        app_name=app_adk.name, user_id=USUARIO, state={CHAVE_APARTAMENTO: corpo.apartamento}
    )
    return {"session_id": sessao.id}


@api.post("/sessoes/{session_id}/mensagens")
async def enviar_mensagem(session_id: str, corpo: Mensagem):
    await _sessao(session_id)
    async with travas[session_id]:
        mensagem = types.Content(role="user", parts=[types.Part(text=corpo.texto)])
        return await _executar(session_id, mensagem)


@api.post("/sessoes/{session_id}/confirmacoes")
async def responder_confirmacao(session_id: str, corpo: RespostaConfirmacao):
    await _sessao(session_id)
    async with travas[session_id]:
        sessao = await _sessao(session_id)
        if corpo.id not in {p["id"] for p in pendencias(sessao)}:
            raise HTTPException(
                status_code=409, detail="Não existe confirmação pendente com esse id nesta sessão."
            )
        resposta = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=corpo.id, name=CONFIRMACAO, response={"confirmed": corpo.confirmado}
                    )
                )
            ],
        )
        return await _executar(session_id, resposta)


@api.get("/sessoes/{session_id}/eventos")
async def eventos(session_id: str):
    sessao = await _sessao(session_id)
    return [e.model_dump(mode="json", exclude_none=True, by_alias=True) for e in sessao.events]


@api.get("/apartamentos/{numero}/reservas")
async def reservas_do_apartamento(numero: str):
    return dados.reservas_do_apartamento(numero)


@api.get("/apartamentos/{numero}/visitantes")
async def visitantes_do_apartamento(numero: str):
    return dados.visitantes_do_apartamento(numero)


def main():
    uvicorn.run("aurora.api:app", host="127.0.0.1", port=8000)
