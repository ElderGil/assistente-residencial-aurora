"""App, Runner e sessão persistida (Garantia 3)."""

from google.adk.apps import App, ResumabilityConfig
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService

from .agentes import concierge
from .config import DB_SESSOES, NOME_APP

# Resumível: a resposta de uma confirmação volta ao especialista que a pediu,
# inclusive numa API recém-reiniciada (decisions/spike-confirmacao.md).
app = App(
    name=NOME_APP,
    root_agent=concierge,
    resumability_config=ResumabilityConfig(is_resumable=True),
)


def criar_runner():
    DB_SESSOES.parent.mkdir(parents=True, exist_ok=True)
    sessoes = DatabaseSessionService(f"sqlite+aiosqlite:///{DB_SESSOES}")
    return Runner(app=app, session_service=sessoes)
