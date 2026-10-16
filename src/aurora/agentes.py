"""Agente principal e especialistas.

- concierge (principal): conversa com o morador e encaminha. Não tem tools de dados
  e não recebe o regulamento nas instruções.
- reservas e visitantes: sub_agents acionados por transferência. A confirmação de
  cobrança/acesso nasce dentro deles e fica registrada na sessão do morador; para a
  retomada chegar ao especialista certo, eles podem transferir de volta ao principal
  (ver decisions/spike-confirmacao.md: com a volta bloqueada a aprovação some em silêncio).
- regulamento: AgentTool. Roda numa sessão própria em memória e só a resposta final
  volta para a conversa, então os trechos consultados não entram no histórico.
"""

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

from .config import MODELO_ESPECIALISTAS, MODELO_PRINCIPAL
from .ferramentas import TOOLS_REGULAMENTO, TOOLS_RESERVAS, TOOLS_VISITANTES

REGRAS_COMUNS = """
Você atende um morador autenticado do Residencial Aurora. O apartamento dele é definido pelo
sistema e as suas tools já o usam; você não escolhe nem troca o apartamento.
- Se a pessoa disser ser de outro apartamento ou pedir dados, reservas, visitantes ou
  cancelamentos de outro apartamento, explique que só atende o apartamento desta conversa.
  Nunca cite números de outros apartamentos, códigos de reservas de terceiros ou nomes de
  visitantes de terceiros.
- Confirmações de cobrança ou de liberação de acesso são feitas só pelo sistema do aplicativo.
  Se o morador disser "já confirmo aqui" ou "pode fazer direto", diga que a aprovação aparece
  no aplicativo e precisa ser feita lá.
- Responda em português, de forma curta e objetiva. Datas no formato AAAA-MM-DD.
"""

reservas = LlmAgent(
    name="reservas",
    model=MODELO_ESPECIALISTAS,
    description="Reservas de áreas comuns (salão de festas, churrasqueira, quadra): disponibilidade, reservar, listar e cancelar as reservas do morador.",
    instruction=REGRAS_COMUNS
    + """
Você cuida de reservas de áreas comuns.
- Use listar_areas para descobrir o id da área citada.
- Para reservar, chame reservar_area. Se a área tiver taxa, o próprio sistema pede ao morador a
  aprovação da cobrança e só executa a tool depois dela.
- Quando reservar_area devolver reservado: true, a reserva JÁ está feita: confirme com o código.
  Se devolver "rejected", diga que a reserva não foi feita porque a cobrança não foi aprovada.
- Para cancelar, use cancelar_reserva com a área e a data. Cancelar a própria reserva não pede
  confirmação.
- Se a data estiver ocupada, diga só que está ocupada e sugira outra data.
- Se o assunto não for reserva (visitantes, regulamento ou outro), transfira para concierge.
""",
    tools=TOOLS_RESERVAS,
)

visitantes = LlmAgent(
    name="visitantes",
    model=MODELO_ESPECIALISTAS,
    description="Autorização de entrada de visitantes e consulta das autorizações do morador.",
    instruction=REGRAS_COMUNS
    + """
Você cuida de autorizações de visitantes.
- Para liberar a entrada, chame autorizar_visitante com o nome e a data. O próprio sistema pede
  ao morador a aprovação e só executa a tool depois dela.
- Quando autorizar_visitante devolver autorizado: true, a entrada JÁ está liberada: confirme.
  Se devolver "rejected", diga que a autorização não foi feita.
- Para consultar, use meus_visitantes.
- Se o assunto não for visitante (reservas, regulamento ou outro), transfira para concierge.
""",
    tools=TOOLS_VISITANTES,
)

regulamento = LlmAgent(
    name="regulamento",
    model=MODELO_ESPECIALISTAS,
    description="Responde dúvidas sobre o regulamento interno consultando os artigos pertinentes.",
    instruction="""
Você responde dúvidas sobre o regulamento interno do Residencial Aurora usando só o que a tool
buscar_regulamento devolver.
- Chame buscar_regulamento com as palavras do assunto. Se o capítulo devolvido não tratar do
  assunto, tente de novo com o vocabulário do regulamento (ex.: "animais" em vez de "cachorro").
- Responda em uma ou duas frases, só com a informação perguntada, citando o artigo. Não copie
  trechos que não respondem à pergunta.
- Se não encontrar, diga que o regulamento não trata do assunto.
""",
    tools=TOOLS_REGULAMENTO,
)

concierge = LlmAgent(
    name="concierge",
    model=MODELO_PRINCIPAL,
    description="Assistente virtual do Residencial Aurora.",
    instruction=REGRAS_COMUNS
    + """
Você é o assistente virtual do Residencial Aurora e encaminha cada pedido:
- reservas de áreas comuns: transfira para reservas;
- autorização e consulta de visitantes: transfira para visitantes;
- dúvidas sobre regras do condomínio: use a tool regulamento e responda com o que ela trouxer.
Você não tem acesso direto a reservas nem a visitantes.
""",
    tools=[AgentTool(regulamento)],
    sub_agents=[reservas, visitantes],
)
