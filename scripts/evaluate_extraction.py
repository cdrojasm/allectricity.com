"""Evalúa la extracción documental contra el conjunto anotado y bloquea regresiones (EG-12).

Uso:
  python scripts/evaluate_extraction.py [--rules-only] [--only 01 02] [--output informe.json]
                                        [--rescore informe.json]
                                        [--baseline evaluation/extraction/baselines/X.json]

El informe guardado con --output sirve como línea base. Con --baseline compara contra esa línea base con evaluation/extraction/thresholds.json y sale
con código 1 si alguna métrica cae más de lo permitido. El modelo y los prompts son los del
entorno (LLM_MODEL, LANGFUSE_PROMPT_LABEL); para comparar modelos, ejecútalo con cada uno.
--rescore vuelve a puntuar un informe guardado con el gold actual, sin llamar al LLM.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.domain.knowledge_graph.evaluation import regressions  # noqa: E402
from src.infrastructure.processing import document_agents  # noqa: E402
from src.infrastructure.processing.extraction_evaluation import (  # noqa: E402
    RULES_ONLY, evaluate, repeated, rescore, summary_table, variance_table,
)

EVALUATION = ROOT / "evaluation" / "extraction"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=EVALUATION / "v1")
    parser.add_argument("--rules-only", action="store_true", help="sin agentes LLM")
    parser.add_argument("--only", nargs="*", help="solo archivos cuyo nombre contenga esto")
    parser.add_argument("--rescore", type=Path, help="informe previo que volver a puntuar")
    parser.add_argument("--output", type=Path, help="guarda el informe completo en JSON")
    parser.add_argument("--baseline", type=Path, help="línea base contra la que comparar")
    parser.add_argument("--thresholds", type=Path, default=EVALUATION / "thresholds.json")
    parser.add_argument("--repeat", type=int, default=1,
                        help="repeticiones de la evaluación para medir la varianza del LLM; el informe guarda la "
                             "media, la dispersión por métrica y cada corrida (thresholds.json puede fijar max_std)")
    args = parser.parse_args()

    agents = RULES_ONLY if args.rules_only else document_agents
    if args.rescore:
        report = rescore(json.loads(args.rescore.read_text(encoding="utf-8")), args.dataset)
    elif not args.rules_only and not document_agents.enabled():
        print("Los agentes LLM no están configurados; usa --rules-only o define "
              "LLM_API_KEY y Langfuse.", file=sys.stderr)
        return 2
    else:
        if args.repeat < 1:
            print("--repeat debe ser al menos 1", file=sys.stderr)
            return 2
        report = repeated([evaluate(args.dataset, ROOT, agents=agents, only=args.only) for _ in range(args.repeat)])
    print(summary_table(report))
    if report.get("variance"):
        print("\n" + variance_table(report))
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    thresholds = json.loads(args.thresholds.read_text(encoding="utf-8"))
    baseline = (json.loads(args.baseline.read_text(encoding="utf-8"))["metrics"]
                if args.baseline else None)
    failures = regressions(report["metrics"], thresholds, baseline, spread=report.get("variance"))
    for failure in failures:
        print(f"REGRESIÓN: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
