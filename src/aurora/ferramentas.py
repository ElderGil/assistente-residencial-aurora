"""Tools dos agentes.

Garantia 2: nenhuma tool recebe apartamento como parâmetro. O apartamento vem sempre
de `tool_context.state["apartamento"]`, gravado uma única vez na criação da sessão
pela API. O que o morador escreve não chega a esse valor.

Garantia 1: `reservar_area` (quando a área tem taxa) e `autorizar_visitante` pedem
confirmação ao sistema via `require_confirmation`. O ADK pausa a execução e só a
retoma quando a API repassa a resposta da rota de confirmações.
"""

from google.adk.tools import FunctionTool, ToolContext

from . import dados, regulamento

CHAVE_APARTAMENTO = "apartamento"


def _apartamento(tool_context):
    return tool_context.state[CHAVE_APARTAMENTO]


def _area_ou_erro(area):
    info = dados.area(area)
    if not info:
        ids = ", ".join(a["id"] for a in dados.areas())
        return None, {"erro": f"Área desconhecida. Use um destes ids: {ids}."}
    return info, None


def listar_areas() -> dict:
    """Lista as áreas comuns reserváveis, com id, nome e taxa em reais (0 = sem cobrança)."""
    return {"areas": dados.areas()}


def consultar_disponibilidade(area: str, data: str) -> dict:
    """Diz se uma área está livre ou ocupada numa data. Não informa de quem é a reserva.

    Args:
      area: id da área (ex.: salao-de-festas, churrasqueira, quadra).
      data: data no formato AAAA-MM-DD.
    """
    _, erro = _area_ou_erro(area)
    if erro:
        return erro
    if not dados.data_valida(data):
        return {"erro": "Data inválida. Use AAAA-MM-DD."}
    return {"area": area, "data": data, "situacao": "livre" if dados.area_livre(area, data) else "ocupada"}


def minhas_reservas(tool_context: ToolContext) -> dict:
    """Lista as reservas ativas do apartamento do morador desta conversa."""
    return {"reservas": dados.reservas_do_apartamento(_apartamento(tool_context))}


def _reserva_tem_taxa(area: str, data: str, tool_context: ToolContext = None) -> bool:
    info = dados.area(area)
    return bool(info and info["taxa"] > 0)


def reservar_area(area: str, data: str, tool_context: ToolContext) -> dict:
    """Reserva uma área comum para o apartamento do morador desta conversa.

    Área com taxa só é reservada depois que o morador aprova a cobrança pelo sistema.

    Args:
      area: id da área (ex.: salao-de-festas, churrasqueira, quadra).
      data: data no formato AAAA-MM-DD.
    """
    info, erro = _area_ou_erro(area)
    if erro:
        return erro
    if not dados.data_valida(data):
        return {"erro": "Data inválida. Use AAAA-MM-DD."}
    resultado = dados.reservar(_apartamento(tool_context), area, data, tool_context.function_call_id)
    if not resultado["ok"]:
        return {"reservado": False, "motivo": "A área já está reservada nessa data. Escolha outra data."}
    return {
        "reservado": True,
        "codigo": resultado["codigo"],
        "area": info["nome"],
        "data": data,
        "taxa": info["taxa"],
    }


def cancelar_reserva(area: str, data: str, tool_context: ToolContext) -> dict:
    """Cancela uma reserva do apartamento do morador desta conversa. Não pede confirmação.

    Args:
      area: id da área (ex.: salao-de-festas, churrasqueira, quadra).
      data: data no formato AAAA-MM-DD.
    """
    _, erro = _area_ou_erro(area)
    if erro:
        return erro
    if dados.cancelar(_apartamento(tool_context), area, data):
        return {"cancelada": True, "area": area, "data": data}
    return {"cancelada": False, "motivo": "Não há reserva sua para essa área nessa data."}


def meus_visitantes(tool_context: ToolContext) -> dict:
    """Lista as autorizações de visita do apartamento do morador desta conversa."""
    return {"visitantes": dados.visitantes_do_apartamento(_apartamento(tool_context))}


def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
    """Autoriza a entrada de um visitante no prédio numa data. Sempre exige aprovação pelo sistema.

    Args:
      nome: nome completo do visitante.
      data: data da visita no formato AAAA-MM-DD.
    """
    if not nome or not nome.strip():
        return {"erro": "Informe o nome do visitante."}
    if not dados.data_valida(data):
        return {"erro": "Data inválida. Use AAAA-MM-DD."}
    r = dados.autorizar_visitante(_apartamento(tool_context), nome.strip(), data, tool_context.function_call_id)
    return {"autorizado": True, "nome": r["nome"], "data": r["data"]}


def buscar_regulamento(assunto: str) -> dict:
    """Busca no regulamento interno os artigos do capítulo que trata do assunto.

    Args:
      assunto: palavras do assunto, de preferência com o vocabulário do regulamento
        (ex.: "piscina domingo horário", "animais de estimação", "obras ruído").
    """
    achado = regulamento.buscar(assunto)
    if not achado:
        return {"encontrado": False}
    return {"encontrado": True, **achado}


# Tools que acionam cobrança ou acesso: confirmação exigida pelo sistema.
TOOLS_RESERVAS = [
    FunctionTool(listar_areas),
    FunctionTool(consultar_disponibilidade),
    FunctionTool(minhas_reservas),
    FunctionTool(reservar_area, require_confirmation=_reserva_tem_taxa),
    FunctionTool(cancelar_reserva),
]
TOOLS_VISITANTES = [
    FunctionTool(meus_visitantes),
    FunctionTool(autorizar_visitante, require_confirmation=True),
]
TOOLS_REGULAMENTO = [FunctionTool(buscar_regulamento)]
