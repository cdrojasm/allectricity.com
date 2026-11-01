import pytest

from src.domain.spat.parametric_geometry import generate_traced_grid
from src.infrastructure.calculations import safety_criteria
from src.infrastructure.calculations.optimizer_evaluation import evaluate_design


TRACED_TEE = {
    "length_m": 10,
    "width_m": 10,
    "burial_depth_m": 0.5,
    "conductors": [
        {"start": {"x": 0, "y": 5}, "end": {"x": 10, "y": 5}},
        {"start": {"x": 5, "y": 5}, "end": {"x": 5, "y": 10}},
    ],
    "rods": [],
}


def test_traced_grid_allows_endpoint_deformation_that_preserves_a_junction():
    result = generate_traced_grid(TRACED_TEE, {
        "conductor_endpoint_deltas": [
            {"start_dy_m": 1, "end_dy_m": 1},
            {"start_dy_m": 1},
        ],
    })

    assert result["conductors"][0]["start"] == {"x": 0.0, "y": 6.0}
    assert result["conductors"][1]["start"] == {"x": 5.0, "y": 6.0}


def test_traced_grid_rejects_endpoint_deformation_that_disconnects_a_junction():
    with pytest.raises(ValueError, match="changes the baseline topology"):
        generate_traced_grid(TRACED_TEE, {
            "conductor_endpoint_deltas": [
                {},
                {"start_dy_m": 1},
            ],
        })


@pytest.mark.parametrize(("geometry", "deltas"), [
    (
        {
            "length_m": 10, "width_m": 10,
            "conductors": [
                {"start": {"x": 0, "y": 5}, "end": {"x": 5, "y": 5}},
                {"start": {"x": 5, "y": 5}, "end": {"x": 5, "y": 10}},
            ],
        },
        [{}, {"start_dy_m": 1}],
    ),
    (
        {
            "length_m": 10, "width_m": 10,
            "conductors": [
                {"start": {"x": 0, "y": 5}, "end": {"x": 10, "y": 5}},
                {"start": {"x": 5, "y": 0}, "end": {"x": 5, "y": 10}},
            ],
        },
        [{}, {"end_dy_m": -6}],
    ),
])
def test_traced_grid_rejects_deformations_that_remove_endpoint_or_crossing_contacts(geometry, deltas):
    with pytest.raises(ValueError, match="changes the baseline topology"):
        generate_traced_grid(geometry, {"conductor_endpoint_deltas": deltas})


def test_variable_bounds_cover_indexed_conductor_and_rod_variables():
    parameters = {
        "conductor_endpoint_deltas": [{}, {"start_dx_m": 0.5}],
        "rod_lengths_m": [3.0],
        "variable_bounds": {
            "conductor_endpoint_deltas[1].start_dx_m": {"min": -1, "max": 0.5},
            "rod_lengths_m[0]": {"min": 2.4, "max": 3.0},
        },
    }
    base = {**TRACED_TEE, "rods": [{"x": 0, "y": 5}]}
    result = generate_traced_grid(base, parameters)
    assert result["rods"][0]["length_m"] == 3.0

    parameters["rod_lengths_m"][0] = 3.01
    with pytest.raises(ValueError, match="is outside"):
        generate_traced_grid(base, parameters)


def test_out_of_bounds_candidate_is_rejected_before_solver_call():
    exposure = safety_criteria.FaultExposure(
        clearing_time_s=0.5,
        body_weight_kg=50,
        surface_resistivity_ohm_m=3000,
        surface_thickness_m=0.1,
        soil_resistivity_ohm_m=100,
    )
    with pytest.raises(ValueError, match="is outside"):
        evaluate_design(
            design_parameters={
                "conductor_endpoint_deltas": [{"start_dx_m": 0.5}, {}],
                "variable_bounds": {
                    "conductor_endpoint_deltas[0].start_dx_m": {"min": 0, "max": 0.25},
                },
            },
            base_geometry=TRACED_TEE,
            soil=100.0,
            injection_a=1.0,
            points=[],
            client=None,
            exposure=exposure,
            standards=[],
        )


def test_traced_grid_rejects_deformation_into_an_obstacle():
    geometry = {
        "length_m": 10,
        "width_m": 10,
        "conductors": [
            {"start": {"x": 0, "y": 2}, "end": {"x": 10, "y": 2}},
        ],
        "rods": [],
        "structures": [{"x": 5, "y": 5, "width": 2, "height": 2}],
    }
    with pytest.raises(ValueError, match="crosses structure"):
        generate_traced_grid(geometry, {
            "conductor_endpoint_deltas": [
                {"start_dy_m": 3, "end_dy_m": 3},
            ],
        })


def test_traced_grid_rejects_deformation_outside_an_intervenible_area():
    geometry = {
        "length_m": 10,
        "width_m": 10,
        "conductors": [
            {"start": {"x": 0, "y": 2}, "end": {"x": 10, "y": 2}},
        ],
        "rods": [],
        "areas": [{"type": "intervenible", "x_min": 0, "x_max": 10, "y_min": 0, "y_max": 3}],
    }
    with pytest.raises(ValueError, match="leaves the intervenible areas"):
        generate_traced_grid(geometry, {"translate_y_m": 2})
