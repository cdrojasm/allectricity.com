from pathlib import Path

from src.infrastructure.processing.extraction_evaluation import RULES_ONLY, evaluate

ROOT = Path(__file__).resolve().parents[2]


def test_rules_only_evaluation_over_text_documents_matches_the_readme():
    """Línea base de las reglas sobre 01–04 (sin OCR): solo equipos con etiqueta."""
    report = evaluate(ROOT / "evaluation" / "extraction" / "v1", ROOT, agents=RULES_ONLY,
                      only=["01_", "02_", "03_", "04_"])
    assert [d["file"][:2] for d in report["documents"]] == ["01", "02", "03", "04"]
    assert report["config"]["method"] == "rules"
    metrics = report["metrics"]
    assert metrics["entities"]["precision"] == 1.0 and metrics["entities"]["tp"] == 4
    assert metrics["invariants"] == {"accepted": 0, "calculation_inputs_not_in_review": 0}
    assert metrics["abstention"] == 1.0
    assert metrics["question_recall"] == 1.0  # alias T-01/T1 sale incluso solo con reglas
    assert metrics["cost"]["llm_tokens"] == 0
