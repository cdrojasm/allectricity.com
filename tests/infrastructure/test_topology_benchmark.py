import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "potential_engine" / "validation"))
import topology_optimizer_benchmark as bench  # noqa: E402
from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient  # noqa: E402

STRATEGIES = ("descent", "uphill", "opportunistic", "adaptive", "alns")


def row(scenario, seed, strategy, cost, **extra):
    blank = {"used": 0, "incumbent": 0, "improving": 0, "novel": 0}
    return {"scenario": scenario, "seed": seed, "strategy": strategy, "budget": 100, "best_cost": cost, "solver_calls": 100, "time_units": 200.0,
            "considered": 150, "confirmed": 5, "demoted": 0, "uphill_moves": 0, "repair_starts": 0, "planning_failures": 0,
            "lns": dict(blank), "atomic": dict(blank), "seconds": 1.0, "budget_exhausted": True, **extra}


def test_the_statistics_compare_strategies_on_equal_footing():
    rows = []
    for seed, descent in enumerate((100.0, 100.0, 100.0, 100.0, 100.0, 100.0)):
        rows += [row("s", seed, "descent", descent), row("s", seed, "uphill", descent - 5.0), row("s", seed, "opportunistic", descent),
                 row("s", seed, "adaptive", descent + 4.0), row("s", seed, "alns", None if seed == 0 else descent - 10.0)]
    result = bench.analyse(rows, STRATEGIES)["overall"]
    assert result["uphill"]["versus_descent"] == {**result["uphill"]["versus_descent"], "better": 6, "equal": 0, "worse": 0}
    assert result["uphill"]["versus_descent"]["sign_test_p"] == pytest.approx(2 * 0.5 ** 6, abs=1e-4)   # reported to 4 decimals
    assert result["opportunistic"]["versus_descent"]["equal"] == 6
    assert result["adaptive"]["versus_descent"]["worse"] == 6 and result["adaptive"]["versus_descent"]["mean_cost_change"] == pytest.approx(0.04)
    assert result["alns"]["feasible"] == 5 and result["alns"]["versus_descent"]["worse"] == 1     # losing feasibility counts as worse
    assert result["alns"]["found_best"] == 5 and result["uphill"]["found_best"] == 1      # seed 0: only uphill has a design, so it sets the best known
    assert result["alns"]["mean_regret"] == pytest.approx(0.0) and result["uphill"]["mean_regret"] == pytest.approx(5 / 90 * 5 / 6, rel=1e-6)
    low, high = result["uphill"]["versus_descent"]["bootstrap95"]
    assert low <= -0.05 <= high or low == high == pytest.approx(-0.05)
    assert result["uphill"]["mean_rank"] > result["alns"]["mean_rank"]


def test_the_exact_sign_test_is_the_textbook_one():
    assert bench._sign_test(0, 0) == 1.0 and bench._sign_test(5, 5) == 1.0
    assert bench._sign_test(8, 0) == pytest.approx(2 / 256) and bench._sign_test(0, 8) == pytest.approx(2 / 256)
    assert bench._sign_test(7, 2) == pytest.approx(2 * sum(math.comb(9, k) for k in range(3)) / 2 ** 9)


def test_the_report_renders_every_strategy_and_scenario():
    rows = [row(sc, sd, st, 100.0 + i) for sc in ("a", "b") for sd in range(3) for i, st in enumerate(STRATEGIES)]
    text = bench.markdown(bench.analyse(rows, STRATEGIES), {"scenarios": 2, "seeds": 3, "strategies": list(STRATEGIES), "budget": 100})
    for name in (*STRATEGIES, "## Overall", "## a", "## b", "What each kind of move earned"):
        assert name in text


def test_every_strategy_runs_on_a_real_scenario_within_the_same_cap():
    if not Path(PotentialEngineClient().executable).is_file():
        pytest.skip("potential engine not built; run `make potential-engine`")
    rows = [bench.run_one({"scenario": "square-building", "seed": 2026, "strategy": s, "budget": 25}) for s in STRATEGIES]
    assert all(r["solver_calls"] <= 25 for r in rows)
    assert {r["strategy"] for r in rows} == set(STRATEGIES)
    assert rows[0]["uphill_moves"] == 0                                    # strict descent never goes uphill
    assert all(r["lns"]["used"] == 0 for r in rows if r["strategy"] != "alns")
