"""Run the slowest tests first.

With pytest-xdist the wall time is set by the last test to finish, so a 50 s test that is handed out at the end of
the run costs 50 s of waiting. Starting the long ones first keeps every worker busy until the very end. The list is
by test id and only changes the order, never what runs; a name that matches nothing is harmless.
"""

SLOW_FIRST = (
    "ieee80_annex_h_grid",               # engine reference cases against IEEE 80 Annex H
    "test_benchmark_reports_every_required_metric",
    "test_every_strategy_runs_on_a_real_scenario",
    "test_an_interrupted_run_resumes_from_its_file",
    "test_topology_search_with_the_real_solver",
    "test_the_best_design_costs_no_more",
    "test_topology_search.py",
    "test_geometry_model.py",
    "test_n_layer_engine.py",
    "test_potential_engine_singularities.py",
)


import pytest


@pytest.fixture(autouse=True)
def openrouter_model(monkeypatch):
    """Agent tests use fake LLM clients, but the code requires a configured model name."""
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/test-model")


def pytest_collection_modifyitems(config, items):
    items.sort(key=lambda item: next((i for i, name in enumerate(SLOW_FIRST) if name in item.nodeid), len(SLOW_FIRST)))
