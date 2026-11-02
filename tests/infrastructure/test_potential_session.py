from pathlib import Path

import pytest
from src.infrastructure.calculations.potential_engine_client import (
    PotentialEngineClient,
    PotentialEngineError,
    PotentialPoint,
    TwoLayerSoil,
    rectangular_grid_segments,
)


@pytest.fixture(scope="module")
def client():
    engine = PotentialEngineClient()
    if not Path(engine.executable).is_file():
        pytest.skip(f"potential engine not built at {engine.executable}; run `make potential-engine`")
    return engine


def _grid():
    return rectangular_grid_segments(
        length_m=20, width_m=20, conductor_spacing_m=5, burial_depth_m=0.5,
        conductor_radius_m=0.00525, rods_count=4, rod_length_m=2.4, discretization_m=2.0,
    )


POINTS = [PotentialPoint(f"p{i}", (i * 1.5 - 12.0, 3.0, 0.0)) for i in range(17)]
SOILS = {"homogeneous": 100.0, "two-layer": TwoLayerSoil(100.0, 300.0, 2.0)}


@pytest.mark.parametrize("name", SOILS)
def test_session_potentials_equal_stateless_calculation(client, name):
    soil, segments = SOILS[name], _grid()
    expected = client.calculate(segments=segments, injections_a={"grid": 1000.0}, points=POINTS, soil=soil)
    with client.session(segments=segments, injections_a={"grid": 1000.0}, soil=soil) as session:
        first = session.evaluate(POINTS)
        # A second query on the same preparation must not change the first answer.
        again = session.evaluate(POINTS[:5])
        assert session.preparations == 1 and session.evaluations == 2
        assert session.currents() == expected["segment_currents_a"]
    assert first == expected["potentials_v"]
    assert again == {pid: expected["potentials_v"][pid] for pid in again}


def test_session_calculate_is_a_drop_in_for_the_client(client):
    segments = _grid()
    expected = client.calculate(segments=segments, injections_a={"grid": 250.0}, points=POINTS, soil=100.0)
    with client.session(segments=segments, injections_a={"grid": 250.0}, soil=100.0) as session:
        same = session.calculate(segments=segments, injections_a={"grid": 250.0}, points=POINTS, soil=100.0)
        other = session.calculate(segments=segments, injections_a={"grid": 500.0}, points=POINTS, soil=100.0)
    assert same["potentials_v"] == expected["potentials_v"]
    assert same["groups"] == expected["groups"]
    # A different injection is a different system: it is solved afresh, not scaled from the session.
    assert other["groups"]["grid"]["injected_current_a"] == 500.0


def test_closed_session_refuses_queries(client):
    session = client.session(segments=_grid(), injections_a={"grid": 1000.0}, soil=100.0)
    session.close()
    with pytest.raises(PotentialEngineError):
        session.evaluate(POINTS)


# ---- sessions are never shared and never leak -------------------------------------------------------------

import copy  # noqa: E402
import pickle  # noqa: E402
import threading  # noqa: E402

from src.infrastructure.calculations.potential_engine_client import PotentialSession  # noqa: E402


def test_a_session_cannot_be_pickled_copied_or_used_from_another_thread(client):
    with client.session(segments=_grid(), injections_a={"grid": 1000.0}, soil=100.0) as session:
        for clone in (pickle.dumps, copy.copy, copy.deepcopy):
            with pytest.raises(TypeError, match="cannot be pickled"):
                clone(session)
        outcome = {}

        def intruder():
            try:
                session.evaluate(POINTS[:2])
                outcome["result"] = "used"
            except PotentialEngineError as error:
                outcome["result"] = str(error)
        thread = threading.Thread(target=intruder)
        thread.start()
        thread.join()
        assert "only be used by the thread and process that opened it" in outcome["result"]
        assert session.evaluate(POINTS[:2])                        # the owner is unaffected


def test_no_engine_session_is_left_open_after_any_evaluation_level_or_a_failure(client, monkeypatch):
    from src.infrastructure.calculations import artifact_potential, solver_evaluation
    geometry = {"length_m": 20, "width_m": 20, "conductor_spacing_m": 5.0, "burial_depth_m": 0.5, "rods_count": 0, "rod_length_m": 2.4}
    before = PotentialSession.open_sessions()
    for level in ("L1", "L2", "L2+", "L3"):
        solver_evaluation.evaluate(geometry=geometry, soil=100.0, injection_a=1000.0, points=[], client=client, level=level)
        assert PotentialSession.open_sessions() == before, level

    def boom(*args, **kwargs):
        raise RuntimeError("mid-evaluation failure")
    monkeypatch.setattr(artifact_potential, "_solve", boom)
    with pytest.raises(RuntimeError):
        solver_evaluation.evaluate(geometry=geometry, soil=100.0, injection_a=1000.0, points=[], client=client, level="L2+")
    assert PotentialSession.open_sessions() == before
