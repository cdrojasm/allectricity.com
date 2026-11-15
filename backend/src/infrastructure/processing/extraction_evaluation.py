"""Ejecuta el pipeline de extracción sobre el conjunto anotado y arma el informe (EG-12).

Cada caso se procesa en orden, como si sus documentos se subieran a un mismo proyecto, con
un grafo en memoria: así la consolidación ve lo extraído antes (alias, conflictos). No toca
Neo4j ni PostgreSQL; el LLM es el configurado en el entorno (o ninguno, solo reglas).
"""

import json
import time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

from src.domain.knowledge_graph.claims import LIVE_STATUSES
from src.domain.knowledge_graph.evaluation import aggregate, score_document
from src.domain.knowledge_graph.taxonomy import TAXONOMY_VERSION
from src.infrastructure.processing import document_agents
from src.infrastructure.processing.knowledge_extraction import extract_knowledge

RULES_ONLY = SimpleNamespace(enabled=lambda: False)
_RUN_FIELDS = ("method", "model", "parser_version", "rules_version", "taxonomy_version",
               "schema_version", "extractor_prompt_name", "extractor_prompt_version",
               "consolidator_prompt_name", "consolidator_prompt_version", "prompt_label")


class _ProjectGraph:
    """Lo mínimo del repositorio del grafo que usa `extract_knowledge`, en memoria."""

    def __init__(self):
        self.runs = {}

    def run_exists(self, run_id):
        return False  # cada evaluación extrae de nuevo

    def project_llm_tokens(self, project_id):
        return sum(run.get("llm_tokens") or 0 for run in self.runs.values())

    def load_project_claims(self, project_id, exclude_open_upload_id=None, limit=5000):
        claims = [dict(claim, filename=run["filename"], upload_id=run["upload_id"])
                  for run in self.runs.values() for claim in run["claims"]
                  if run["upload_id"] != exclude_open_upload_id]
        return [claim for claim in claims if claim["status"] in LIVE_STATUSES][:limit]

    def save_run(self, run):
        self.runs[run["run_id"]] = run
        return True


def load_dataset(dataset_dir: Path) -> dict:
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    for case in manifest["cases"]:
        case["gold"] = [json.loads((dataset_dir / name).read_text(encoding="utf-8"))
                        for name in case["documents"]]
    return manifest


def evaluate(dataset_dir: Path, root: Path, agents=document_agents, only=None) -> dict:
    """Informe completo: configuración, resultado por documento y métricas agregadas."""
    manifest = load_dataset(dataset_dir)
    documents, config = [], {}
    for case in manifest["cases"]:
        graph = _ProjectGraph()
        for index, gold in enumerate(case["gold"], start=1):
            name = Path(gold["file"]).name
            if only and not any(token in name for token in only):
                continue
            upload = {"id": f"{case['id']}-{index:02d}", "project_id": f"eval-{case['id']}",
                      "owner_id": "evaluation", "filename": name, "object_key": gold["file"]}
            started = time.monotonic()
            _, summary = extract_knowledge(upload, (root / gold["file"]).read_bytes(),
                                           gold["mime_type"], graph, agents=agents)
            elapsed = round(time.monotonic() - started, 3)
            run = graph.runs[summary["run_id"]]
            config = config or {key: run.get(key) for key in _RUN_FIELDS}
            documents.append({
                "case": case["id"], "file": name, "gold": gold, "doc_type": gold["doc_type"],
                "status": run["status"], "duration_seconds": elapsed,
                "llm_tokens": run["llm_tokens"], "llm_cost_usd": run["llm_cost_usd"],
                "rejected": run["rejected"], "run_errors": run["errors"][:20],
                "claims": [_compact(claim) for claim in run["claims"]],
                "questions": [{"kind": q["kind"], "question": q["question"]}
                              for q in run["questions"]],
            })
    return _report(manifest, config, documents)


def rescore(report: dict, dataset_dir: Path) -> dict:
    """Vuelve a puntuar las afirmaciones guardadas en un informe con el gold actual, sin
    volver a extraer: sirve para corregir el conjunto anotado sin pagar otra pasada LLM."""
    manifest = load_dataset(dataset_dir)
    gold = {(case["id"], Path(item["file"]).name): item
            for case in manifest["cases"] for item in case["gold"]}
    documents = [dict(document, gold=gold[(document["case"], document["file"])])
                 for document in report["documents"]]
    return _report(manifest, report["config"], documents)


def _compact(claim: dict) -> dict:
    """Lo que necesita la puntuación (y una persona para auditarla), sin offsets internos."""
    keep = ("kind", "status", "entity_type", "name", "aliases", "subject_name", "attribute",
            "value_literal", "unit_literal", "value_si", "qualifier", "feeds_calculation",
            "relation_type", "symmetric", "source_type", "source_name", "target_type",
            "target_name", "methods", "review_reasons")
    return {**{key: claim[key] for key in keep if key in claim},
            "evidence": [{"quote": r["quote"], "locator": r["locator"]}
                         for r in claim.get("evidence", [])]}


def _report(manifest: dict, config: dict, documents: list) -> dict:
    for document in documents:
        gold = document.pop("gold")
        document["score"] = score_document(gold, document["claims"], document["questions"])
        document["metrics"] = aggregate([document["score"]])
    by_type = defaultdict(list)
    for document in documents:
        by_type[document["doc_type"]].append(document["score"])
    costs = [d["llm_cost_usd"] for d in documents if d["llm_cost_usd"] is not None]
    metrics = aggregate([d["score"] for d in documents])
    metrics["cost"] = {
        "llm_tokens": sum(d["llm_tokens"] for d in documents),
        "llm_cost_usd": round(sum(costs), 6) if costs else None,
        "duration_seconds": round(sum(d["duration_seconds"] for d in documents), 3),
        "documents": len(documents),
    }
    return {
        "dataset": manifest["version"], "dataset_review": manifest.get("review", {}),
        "taxonomy_version": config.get("taxonomy_version") or TAXONOMY_VERSION,
        "created_at": int(time.time()),
        "config": config, "metrics": metrics,
        "by_doc_type": {doc_type: aggregate(scores) for doc_type, scores in sorted(by_type.items())},
        "documents": documents,
    }


def repeated(reports: list[dict]) -> dict:
    """Un informe a partir de N repeticiones de la misma evaluación (EG-12, varianza).

    `metrics` y `by_doc_type` son el promedio; `variance` guarda media, desviación, mínimo y máximo de cada
    métrica entre repeticiones; `runs` conserva las métricas de cada repetición; `documents` son los de la
    primera (los claims extraídos no se promedian). Con un solo informe lo devuelve tal cual.
    """
    from src.domain.knowledge_graph.evaluation import mean_metrics, variance

    if len(reports) == 1:
        return reports[0]
    first = reports[0]
    return {
        **first,
        "metrics": mean_metrics([r["metrics"] for r in reports]),
        "by_doc_type": mean_metrics([r["by_doc_type"] for r in reports]),
        "variance": variance([r["metrics"] for r in reports]),
        "runs": [{"created_at": r["created_at"], "metrics": r["metrics"]} for r in reports],
        "repetitions": len(reports),
    }


def variance_table(report: dict, paths=("overall.f1", "entities.recall", "attributes.precision", "attributes.recall",
                                        "relations.precision", "relations.recall", "evidence_accuracy", "question_recall",
                                        "cost.llm_tokens", "cost.llm_cost_usd")) -> str:
    """Dispersión entre repeticiones de las métricas que vigilan los umbrales."""
    spread = report.get("variance")
    if not spread:
        return ""
    lines = [f"Varianza entre {report.get('repetitions')} repeticiones", "", "| Métrica | Media | Desv. | Mín. | Máx. |", "|---|---|---|---|---|"]
    for path in paths:
        stats = spread.get(path)
        if stats:
            lines.append(f"| {path} | {stats['mean']:.4g} | {stats['std']:.4g} | {stats['min']:.4g} | {stats['max']:.4g} |")
    return "\n".join(lines)


def summary_table(report: dict) -> str:
    """Resumen legible del informe para la terminal."""
    def pct(value):
        return "—" if value is None else f"{value * 100:.0f} %"

    config = report["config"]
    lines = [f"Conjunto {report['dataset']} · método {config.get('method')} · modelo "
             f"{config.get('model') or '—'} · prompt {config.get('extractor_prompt_version') or '—'}",
             "", "| Documento | Entidades P/R | Atributos P/R | Relaciones P/R | Evidencia | "
             "Tokens | s |", "|---|---|---|---|---|---|---|"]
    rows = [(d["file"], d["metrics"], d["llm_tokens"], d["duration_seconds"])
            for d in report["documents"]]
    rows.append(("**Total**", report["metrics"], report["metrics"]["cost"]["llm_tokens"],
                 report["metrics"]["cost"]["duration_seconds"]))
    for name, metrics, tokens, seconds in rows:
        cells = [f"{pct(metrics[k]['precision'])} / {pct(metrics[k]['recall'])}"
                 for k in ("entities", "attributes", "relations")]
        lines.append(f"| {name} | {' | '.join(cells)} | {pct(metrics['evidence_accuracy'])} | "
                     f"{tokens} | {seconds} |")
    metrics = report["metrics"]
    lines += ["", f"F1 global {pct(metrics['overall']['f1'])} · duplicados {metrics['duplicates']}"
              f" · abstención {pct(metrics['abstention'])} · preguntas "
              f"{pct(metrics['question_recall'])} · invariantes {metrics['invariants']}"
              f" · coste {metrics['cost']['llm_cost_usd'] or '—'} USD"]
    return "\n".join(lines)
