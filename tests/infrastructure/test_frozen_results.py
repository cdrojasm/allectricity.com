"""SV-27: the engine reproduces the frozen results of every reference case for its solver version.

Any difference fails here with the list of what moved. The frozen file is regenerated only with a change of
`kSolverVersion` (see services/potential_engine/validation/freeze_results.py and BACKLOG_SOLVER SV-27).
"""

import importlib.util
import json
from pathlib import Path

import pytest
from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient
from src.infrastructure.calculations.potential_engine_validation import load_cases

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "services" / "potential_engine" / "validation" / "freeze_results.py"
FROZEN = ROOT / "services" / "potential_engine" / "validation" / "frozen_results.json"
DEFAULT_CASES_PATH = ROOT / "services" / "potential_engine" / "validation" / "reference_cases.json"


def _module():
    spec = importlib.util.spec_from_file_location("freeze_results", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def engine():
    client = PotentialEngineClient()
    if not Path(client.executable).is_file():
        pytest.skip("potential engine not built; run `make potential-engine`")
    return client


def test_the_frozen_file_covers_every_reference_case_and_states_its_rule():
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    assert frozen["records"], "no frozen record: run freeze_results.py --write"
    assert "kSolverVersion" in frozen["rule"] and "PE-04" in frozen["rule"]
    case_ids = {case["id"] for case in load_cases(DEFAULT_CASES_PATH)["cases"]}
    latest = frozen["records"][-1]
    assert set(latest["cases"]) == case_ids
    assert latest["frozen_on"] and latest["reason"] and latest["solver_version"]
    versions = [record["solver_version"] for record in frozen["records"]]
    assert len(versions) == len(set(versions)), "one record per solver version"


def test_the_engine_reproduces_the_frozen_results_of_its_solver_version(engine):
    freeze = _module()
    current = freeze.compute(engine, load_cases(DEFAULT_CASES_PATH))
    frozen = freeze.load_frozen(FROZEN)
    record = freeze.latest_record(frozen, current["solver_version"])
    assert record is not None, (f"solver {current['solver_version']} has no frozen record; the version changed, so "
                                "record the change in PE-04 and run freeze_results.py --write")
    diff = freeze.differences(record, current)
    assert not diff, "the engine no longer reproduces its frozen results; explain or re-freeze with a new version:\n" + "\n".join(diff)


def test_differences_are_reported_per_case_and_quantity():
    freeze = _module()
    frozen = {"solver_version": "v", "cases": {"a": {"values": [{"quantity": "resistance_ohm", "label": None, "value": 1.0}],
                                                       "segment_count": 10, "backward_error": 1e-12}}}
    same = {"solver_version": "v", "cases": {"a": {"values": [{"quantity": "resistance_ohm", "label": None, "value": 1.0 + 1e-9}],
                                                     "segment_count": 10, "backward_error": 1e-12}}}
    assert freeze.differences(frozen, same) == []
    moved = {"solver_version": "w", "cases": {"a": {"values": [{"quantity": "resistance_ohm", "label": None, "value": 1.01}],
                                                      "segment_count": 12, "backward_error": 1e-6}, "b": {"values": [], "segment_count": 1, "backward_error": 0}}}
    diff = freeze.differences(frozen, moved)
    assert diff[0].startswith("solver version v -> w") and any("segment count 10 -> 12" in d for d in diff)
    assert any("resistance_ohm 1 -> 1.01" in d for d in diff) and any("backward error" in d for d in diff) and any("b: not frozen" in d for d in diff)
