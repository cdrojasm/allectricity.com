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
