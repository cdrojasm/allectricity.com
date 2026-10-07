from dataclasses import dataclass
from src.application.use_cases.identity import IdentityService
from src.application.use_cases.identity_admin import IdentityAdmin
from src.application.use_cases.budgets import Budgets
from src.infrastructure.persistence.identity_store import SQLIdentityStore
from src.infrastructure.persistence.knowledge_graph_store import Neo4jKnowledgeGraph
from src.infrastructure.security.providers import (
    HS256Tokens,
    ArgonPasswords,
    GoogleIdentity,
    FernetMessages,
)


@dataclass
class Services:
    identity: IdentityService
    admin: IdentityAdmin
    budgets: Budgets
    store: SQLIdentityStore
    knowledge_graph: Neo4jKnowledgeGraph | None = None


def build_services(settings):
    store = SQLIdentityStore(settings.database_url)
    passwords = ArgonPasswords()
    identity = IdentityService(
        store,
        HS256Tokens(settings),
        passwords,
        GoogleIdentity(settings.google_client_id),
        FernetMessages(settings.mail_key),
        settings,
    )
    return Services(identity, IdentityAdmin(store, passwords), Budgets(store), store,
                    Neo4jKnowledgeGraph.from_env())
