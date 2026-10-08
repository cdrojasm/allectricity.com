import io

import pytest

from src.application.use_cases.knowledge_review import KnowledgeReview
from src.domain.knowledge_graph.claims import (
    ACCEPTED, NEEDS_REVIEW, PROPOSED, ReviewError, SUPERSEDED,
)
from src.infrastructure.processing.document_sources import DOCX_MIME
from src.infrastructure.processing.knowledge_extraction import extract_knowledge
from tests.infrastructure.fake_knowledge_graph import InMemoryKnowledgeGraph


def docx(*paragraphs) -> bytes:
    from docx import Document

    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def upload(upload_id="u1", filename="memoria.docx"):
    return {"id": upload_id, "project_id": "project-1", "owner_id": "user-1",
            "filename": filename, "object_key": f"user-1/{upload_id}.docx"}


class FakeAgents:
    def __init__(self, payload=None, version=1, fail=False):
        self.payload, self.version, self.fail = payload, version, fail
        self.extractions, self.limits = 0, []

    def enabled(self):
        return True

    def load_prompts(self):
        return {"meta": {"extractor_prompt_name": "spat-document-extractor",
                         "extractor_prompt_version": self.version,
                         "consolidator_prompt_name": "spat-document-consolidator",
                         "consolidator_prompt_version": 1, "prompt_label": "test",
                         "model": "fake-model"}}

    def run_llm_extraction(self, source, rule_payload, filename, prompts, max_tokens=None):
        self.extractions += 1
        self.limits.append(max_tokens)
        if self.fail:
            raise TimeoutError("provider down")
        if isinstance(self.payload, dict) and "schema_version" in self.payload:
            return {"payload": self.payload, "errors": [],
                    "usage": {"rounds": 2, "prompt_tokens": 1000, "completion_tokens": 200}}
        return {"payload": None, "errors": ["(raíz): 'entities' is a required property"],
                "usage": {"rounds": 3}}

    def run_llm_consolidation(self, source, claims, questions, context, filename, prompts,
                              max_tokens=None):
        self.limits.append(max_tokens)
        return {"review_claim_ids": [], "questions": [], "summary": "Resumen de prueba",
                "usage": {"rounds": 1, "prompt_tokens": 300, "completion_tokens": 50}}


MEMORIA = docx("El transformador T1, 13,8 kV, alimenta el tablero TD-2.",
               "Corriente de cortocircuito 20 kA en el transformador T1.")
LLM_PAYLOAD = {
    "schema_version": "1.0",
    "entities": [
        {"id": "e1", "type": "Transformer", "name": "T1",
         "confidence": {"level": "high", "reason": "Etiqueta explícita"}},
        {"id": "e2", "type": "ElectricalPanel", "name": "TD-2",
         "confidence": {"level": "high", "reason": "Etiqueta explícita"}},
    ],
    "attributes": [
        {"id": "a1", "subject_id": "e1", "name": "rated_voltage", "value": "13,8", "unit": "kV",
         "confidence": {"level": "high", "reason": "Junto al equipo"}},
    ],
    "relations": [
        {"id": "r1", "type": "SUPPLIES", "source_id": "e1", "target_id": "e2",
         "confidence": {"level": "medium", "reason": "«alimenta»"}},
    ],
    "evidence": [
        {"finding_ids": ["e1", "e2", "a1", "r1"],
         "quote": "El transformador T1, 13,8 kV, alimenta el tablero TD-2",
         "locator": {"segment": "para1"}},
    ],
    "uncertainties": [],
}


class Disabled:
    @staticmethod
    def enabled():
        return False


def by_content(graph):
    result = {}
    for claim in graph.claims.values():
        label = claim.get("attribute") or claim.get("relation_type") or claim.get("name")
        result.setdefault(label, []).append(claim)
    return result


def test_rules_only_extraction_proposes_but_never_accepts():
    graph = InMemoryKnowledgeGraph()
    source, run = extract_knowledge(upload(), MEMORIA, DOCX_MIME, graph, agents=Disabled)
    claims = by_content(graph)
    assert claims["T1"][0]["status"] == PROPOSED
    fault = claims["fault_current"][0]
    assert fault["status"] == NEEDS_REVIEW and fault["value_si"] == 20000
    assert fault["evidence"][0]["locator"]["paragraph"] == 2
    assert all(claim["status"] != ACCEPTED for claim in graph.claims.values())
    assert run["status"] == "completed" and source.complete


def test_llm_findings_merge_with_rules_and_retries_are_idempotent():
    graph, agents = InMemoryKnowledgeGraph(), FakeAgents(LLM_PAYLOAD)
    _, first = extract_knowledge(upload(), MEMORIA, DOCX_MIME, graph, agents=agents)
    claims = by_content(graph)
    assert claims["SUPPLIES"][0]["status"] == NEEDS_REVIEW
    assert set(claims["T1"][0]["methods"]) == {"rules", "llm"}
    assert graph.runs[first["run_id"]]["method"] == "rules+llm"
    assert graph.runs[first["run_id"]]["metrics"]["usage"]["extractor"]["rounds"] == 2

    _, second = extract_knowledge(upload(), MEMORIA, DOCX_MIME, graph, agents=agents)
    assert second == {"run_id": first["run_id"], "status": "already_processed"}
    assert graph.saves == 1 and agents.extractions == 1


def test_new_prompt_version_supersedes_open_claims_but_keeps_decisions():
    graph = InMemoryKnowledgeGraph()
    _, first = extract_knowledge(upload(), MEMORIA, DOCX_MIME, graph,
                                 agents=FakeAgents(LLM_PAYLOAD, version=1))
    voltage = by_content(graph)["rated_voltage"][0]
    KnowledgeReview(graph).decide("project-1", voltage["claim_id"], "reviewer", "accept",
                                  "Coincide con la placa")
    _, second = extract_knowledge(upload(), MEMORIA, DOCX_MIME, graph,
                                  agents=FakeAgents(LLM_PAYLOAD, version=2))
    assert second["run_id"] != first["run_id"]
    old = [c for c in graph.claims.values() if c["run_id"] == first["run_id"]]
    assert {c["status"] for c in old if c["claim_id"] != voltage["claim_id"]} == {SUPERSEDED}
    assert graph.claims[voltage["claim_id"]]["status"] == ACCEPTED
    new_voltage = [c for c in by_content(graph)["rated_voltage"]
                   if c["run_id"] == second["run_id"]][0]
    assert new_voltage["duplicate_of"] == [voltage["claim_id"]]


def test_taxonomy_version_is_part_of_the_run_identity(monkeypatch):
    from src.infrastructure.processing import knowledge_extraction

    graph = InMemoryKnowledgeGraph()
    _, first = extract_knowledge(upload(), MEMORIA, DOCX_MIME, graph, agents=FakeAgents(LLM_PAYLOAD))
    assert graph.runs[first["run_id"]]["taxonomy_version"] == knowledge_extraction.TAXONOMY_VERSION
    monkeypatch.setattr(knowledge_extraction, "TAXONOMY_VERSION", "taxonomy/test")
    _, second = extract_knowledge(upload(), MEMORIA, DOCX_MIME, graph, agents=FakeAgents(LLM_PAYLOAD))
    assert second["run_id"] != first["run_id"] and second["status"] != "already_processed"


def test_conflicting_documents_require_explicit_human_replacement():
    graph = InMemoryKnowledgeGraph()
    extract_knowledge(upload(), MEMORIA, DOCX_MIME, graph, agents=FakeAgents(LLM_PAYLOAD))
    first = by_content(graph)["rated_voltage"][0]
    review = KnowledgeReview(graph)
    review.decide("project-1", first["claim_id"], "reviewer", "accept", "Memoria aprobada")

    other = dict(LLM_PAYLOAD, evidence=[dict(LLM_PAYLOAD["evidence"][0],
                                              quote=LLM_PAYLOAD["evidence"][0]["quote"]
                                              .replace("13,8", "13,2"))],
                 attributes=[dict(LLM_PAYLOAD["attributes"][0], value="13,2")])
    extract_knowledge(upload("u2", "placa.docx"),
                      docx("El transformador T1, 13,2 kV, alimenta el tablero TD-2."),
                      DOCX_MIME, graph, agents=FakeAgents(other))
    second = [c for c in by_content(graph)["rated_voltage"] if c["upload_id"] == "u2"][0]
    assert second["status"] == NEEDS_REVIEW and second["contradicts"] == [first["claim_id"]]
    question = next(q for q in graph.questions.values() if q["kind"] == "conflict")
    assert set(question["claim_ids"]) == {first["claim_id"], second["claim_id"]}

    with pytest.raises(ReviewError) as error:
        review.decide("project-1", second["claim_id"], "reviewer", "accept", "Placa en sitio")
    assert error.value.code == "conflict"
    assert graph.claims[first["claim_id"]]["status"] == ACCEPTED

    review.decide("project-1", second["claim_id"], "reviewer", "accept", "Placa en sitio",
                  supersede_claim_ids=[first["claim_id"]])
    assert graph.claims[first["claim_id"]]["status"] == SUPERSEDED
    assert graph.claims[first["claim_id"]]["value_literal"] == "13,8"


def test_corrections_keep_proposed_value_and_relations_materialize_on_accept():
    graph = InMemoryKnowledgeGraph()
    extract_knowledge(upload(), MEMORIA, DOCX_MIME, graph, agents=FakeAgents(LLM_PAYLOAD))
    review = KnowledgeReview(graph)
    voltage = by_content(graph)["rated_voltage"][0]
    corrected = review.decide("project-1", voltage["claim_id"], "reviewer", "correct",
                              "La placa indica 13,2 kV", corrected_value="13,2")
    assert corrected["value_literal"] == "13,8" and corrected["reviewed_value_literal"] == "13,2"
    assert corrected["decisions"][0]["previous_status"] == NEEDS_REVIEW

    relation = by_content(graph)["SUPPLIES"][0]
    review.decide("project-1", relation["claim_id"], "reviewer", "accept", "Unifilar")
    assert len(graph.edges) == 1
    review.decide("project-1", relation["claim_id"], "reviewer", "reject", "Error de lectura")
    assert graph.edges == set()


def test_invalid_llm_output_is_recorded_and_rules_still_persist():
    graph = InMemoryKnowledgeGraph()
    _, run = extract_knowledge(upload(), MEMORIA, DOCX_MIME, graph, agents=FakeAgents("bad"))
    stored = graph.runs[run["run_id"]]
    assert stored["status"] == "completed_with_errors"
    assert stored["errors"][0].startswith("extractor LLM:")
    assert "T1" in by_content(graph)


def test_provider_failures_are_retryable():
    with pytest.raises(RuntimeError):
        extract_knowledge(upload(), MEMORIA, DOCX_MIME, InMemoryKnowledgeGraph(),
                          agents=FakeAgents(LLM_PAYLOAD, fail=True))


def test_llm_tokens_and_cost_are_recorded(monkeypatch):
    monkeypatch.setenv("LLM_PRICE_INPUT_USD_PER_MTOK", "0.15")
    monkeypatch.setenv("LLM_PRICE_OUTPUT_USD_PER_MTOK", "0.60")
    graph = InMemoryKnowledgeGraph()
    _, run = extract_knowledge(upload(), MEMORIA, DOCX_MIME, graph, agents=FakeAgents(LLM_PAYLOAD))
    stored = graph.runs[run["run_id"]]
    assert stored["llm_tokens"] == 1550 and run["metrics"]["llm_tokens"] == 1550
    assert stored["llm_cost_usd"] == round((1300 * 0.15 + 250 * 0.60) / 1e6, 6)
    assert graph.project_llm_tokens("project-1") == 1550


def test_token_limits_split_between_agents_and_exhausted_project_uses_rules(monkeypatch):
    monkeypatch.setenv("DOCUMENT_LLM_MAX_TOKENS_PER_FILE", "5000")
    monkeypatch.setenv("DOCUMENT_LLM_MAX_TOKENS_PER_PROJECT", "6000")
    graph = InMemoryKnowledgeGraph()
    agents = FakeAgents(LLM_PAYLOAD)
    extract_knowledge(upload(), MEMORIA, DOCX_MIME, graph, agents=agents)
    # El consolidador recibe lo que dejó el extractor dentro del límite por archivo.
    assert agents.limits == [5000, 5000 - 1200]

    # Quedan 6000 - 1550 = 4450 tokens del proyecto para el siguiente archivo.
    second = FakeAgents(LLM_PAYLOAD)
    extract_knowledge(upload("u2"), MEMORIA, DOCX_MIME, graph, agents=second)
    assert second.limits[0] == 4450

    monkeypatch.setenv("DOCUMENT_LLM_MAX_TOKENS_PER_PROJECT", "3100")
    third = FakeAgents(LLM_PAYLOAD)
    _, run = extract_knowledge(upload("u3"), MEMORIA, DOCX_MIME, graph, agents=third)
    stored = graph.runs[run["run_id"]]
    assert third.extractions == 0 and stored["method"] == "rules"
    assert stored["status"] == "completed_with_errors"
    assert "límite de tokens LLM del proyecto agotado" in stored["errors"][0]
    assert "T1" in by_content(graph)
