import sys
from pathlib import Path

import pytest

VALIDATION = Path(__file__).resolve().parents[2] / "services" / "potential_engine" / "validation"
sys.path.insert(0, str(VALIDATION))
import free_geometry_benchmark as bench  # noqa: E402
import free_geometry_generator as generator  # noqa: E402
from src.domain.spat.optimizer_constraints import evaluate_optimizer_geometry  # noqa: E402
from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient  # noqa: E402


def test_suite_is_reproducible_from_its_seeds_and_covers_every_family():
    first = bench.build_suite([7, 8], per_family=2)
    assert bench.suite_sha256(first) == bench.suite_sha256(bench.build_suite([7, 8], per_family=2))
    assert bench.suite_sha256(first) != bench.suite_sha256(bench.build_suite([7, 9], per_family=2))
    assert {d["seed"] for d in first} == {7, 8}
    assert {d["family"] for d in first} == set(generator.FAMILIES)
    assert {d["soil"] for d in first} <= {"homog", "2layer"}
    assert all(evaluate_optimizer_geometry(d["geometry"])["status"] == "valid" for d in first)


def test_benchmark_reports_every_required_metric_for_a_small_suite():
    if not Path(PotentialEngineClient().executable).is_file():
        pytest.skip("potential engine not built; run `make potential-engine`")
    suite = bench.build_suite([3], per_family=2)
    jobs = [{"key": f"{d['seed']}:{d['index']}", **{k: d[k] for k in ("family", "soil", "geometry")}} for d in suite]
    rows = [bench.evaluate_design_levels(job) for job in jobs]
    fine = {r["key"]: bench.fine_reference(job) for r, job in list(zip(rows, jobs))[:2] if "L2" in r}
    result = bench.report(rows, fine)
    assert result["l2plus_below_l1_or_l2"] == 0
    assert set(result["errors_by_family"]) == set(generator.FAMILIES)
    for level in bench.LEVELS:
        assert {"median", "p5", "worst", "short_over_2pct"} <= set(result["underestimation"][level]["Vt"]["all"])
        assert "spearman_vs_best_known" in result["ranking"][level]
        assert result["time_s"][level]["total"] > 0
    for exposure in result["false_compliance"].values():
        assert set(exposure) == {"20% violating", "50% violating", "80% violating"}
    assert "| family |" in bench.markdown(result, {"seeds": [3], "geometry_set_sha256": bench.suite_sha256(suite)})
