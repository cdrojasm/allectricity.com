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


def test_repeating_a_deterministic_evaluation_reports_zero_variance_and_keeps_the_report_shape():
    from src.infrastructure.processing.extraction_evaluation import repeated, variance_table

    one = evaluate(ROOT / "evaluation" / "extraction" / "v1", ROOT, agents=RULES_ONLY, only=["01_", "02_"])
    assert repeated([one]) is one
    report = repeated([one, evaluate(ROOT / "evaluation" / "extraction" / "v1", ROOT, agents=RULES_ONLY, only=["01_", "02_"])])
    assert report["repetitions"] == 2 and len(report["runs"]) == 2 and report["documents"] == one["documents"]
    assert report["metrics"]["entities"]["precision"] == one["metrics"]["entities"]["precision"]
    # Only the wall-clock duration may differ between two deterministic runs.
    assert all(stats["std"] == 0.0 and stats["n"] == 2 for path, stats in report["variance"].items() if path != "cost.duration_seconds")
    assert "| overall.f1 |" in variance_table(report) and variance_table(one) == ""
