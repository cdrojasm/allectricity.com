import pytest

from src.domain.spat.grid_geometry import (
    axis_positions, conductor_lines, geometry_problems, missing_for_calculation, rod_layout, rod_points, split_lines,
)
from src.infrastructure.calculations.artifact_potential import _segments
from src.infrastructure.calculations.potential_engine_client import (
    HomogeneousSoil, TwoLayerSoil, interface_depths, rectangular_grid_segments,
)

REGULAR = {"length_m": 40, "width_m": 30, "conductor_spacing_m": 5, "burial_depth_m": 0.5,
           "rods_count": 8, "rod_length_m": 2.4}


def test_spacing_per_axis():
    geometry = {"length_m": 40, "width_m": 30, "conductor_spacing_x_m": 4, "conductor_spacing_y_m": 6}
    lines = conductor_lines(geometry)
    along_x = [line for line in lines if line[0][1] == line[1][1]]
    along_y = [line for line in lines if line[0][0] == line[1][0]]
    assert len(along_y) == 11 and len(along_x) == 6  # every 4 m along X, every 6 m along Y
    assert axis_positions(30, 7) == [0.0, 6.0, 12.0, 18.0, 24.0, 30.0]  # never further apart than requested
    assert geometry_problems(geometry) == []
    assert geometry_problems({"length_m": 40, "width_m": 30, "conductor_spacing_y_m": 6})  # X spacing missing


def test_explicit_conductors_and_rods():
    l_shape = {"length_m": 20, "width_m": 20, "conductors": [
        {"start": {"x": 0, "y": 0}, "end": {"x": 20, "y": 0}},
        {"start": {"x": 0, "y": 0}, "end": {"x": 0, "y": 20}},
        {"start": {"x": 0, "y": 20}, "end": {"x": 10, "y": 20}},
        {"start": {"x": 20, "y": 0}, "end": {"x": 20, "y": 10}},
        {"start": {"x": 10, "y": 10}, "end": {"x": 20, "y": 10}},
        {"start": {"x": 10, "y": 10}, "end": {"x": 10, "y": 20}},
    ], "rods": [{"x": 0, "y": 0}, {"x": 10, "y": 10, "length_m": 3}]}
    assert geometry_problems(l_shape) == []
    assert rod_points(l_shape)[1] == (10, 10, 3.0)
    bad = {**l_shape, "rods": [{"x": 15, "y": 15}],
           "conductors": l_shape["conductors"] + [{"start": {"x": 2, "y": 0}, "end": {"x": 30, "y": 0}}]}
    problems = geometry_problems(bad)
    assert any("leaves the grid outline" in p for p in problems)
    assert any("overlap" in p for p in problems)
    assert any("does not touch any conductor" in p for p in problems)


def test_rod_layouts():
    assert len(rod_layout("corners", REGULAR)) == 4
    assert len(rod_layout("grid_nodes", REGULAR)) == 9 * 7
    assert len(rod_layout("perimeter_nodes", REGULAR)) == 2 * 9 + 2 * 5
    lattice = rod_layout("lattice_perimeter", REGULAR, 10, 15)
    assert {(r["x"], r["y"]) for r in lattice} >= {(0.0, 0.0), (40.0, 30.0), (10.0, 0.0), (0.0, 15.0)}
    with pytest.raises(ValueError):
        rod_layout("lattice", REGULAR)


def test_split_lines_cuts_crossings_t_junctions_and_rod_tops():
    lines = [((0, 0), (10, 0)), ((5, 0), (5, 10)), ((0, 5), (10, 5))]
    pieces = split_lines(lines, [(2.5, 0)])
    assert ((0.0, 0.0), (2.5, 0.0)) in pieces and ((2.5, 0.0), (5.0, 0.0)) in pieces
    assert ((5.0, 0.0), (5.0, 5.0)) in pieces and ((5.0, 5.0), (5.0, 10.0)) in pieces
    assert len(pieces) == 3 + 2 + 2


@pytest.mark.parametrize("soil", [HomogeneousSoil(100.0), TwoLayerSoil(300.0, 100.0, 1.5)])
@pytest.mark.parametrize("segmentation", ["uniform", "graded"])
def test_network_path_matches_the_regular_mesh(soil, segmentation):
    """Drawing the regular mesh as explicit conductors gives the same engine segments."""
    parameters = {"discretization_m": 1.0, "conductor_radius_m": 0.005, "segmentation": segmentation}
    regular = rectangular_grid_segments(
        length_m=40, width_m=30, conductor_spacing_m=5, burial_depth_m=0.5, conductor_radius_m=0.005,
        rods_count=0, discretization_m=1.0, interface_depths_m=interface_depths(soil), segmentation=segmentation)
    drawn = {**REGULAR, "rods_count": 0, "conductors": [
        {"start": {"x": a[0], "y": a[1]}, "end": {"x": b[0], "y": b[1]}} for a, b in conductor_lines(REGULAR)]}
    network = _segments(drawn, parameters, soil)

    def key(segments):
        return sorted(tuple(sorted((tuple(round(c, 6) for c in s.start_m), tuple(round(c, 6) for c in s.end_m))))
                      for s in segments)

    assert key(network) == key(regular)


def test_rods_on_network_are_cut_at_soil_interfaces():
    soil = TwoLayerSoil(300.0, 100.0, 1.5)
    geometry = {**REGULAR, "conductor_spacing_x_m": 4, "conductor_spacing_y_m": 6,
                "rods": rod_layout("corners", REGULAR)}
    segments = _segments(geometry, {"discretization_m": 1.0, "conductor_radius_m": 0.005,
                                    "segmentation": "graded"}, soil)
    rods = [s for s in segments if s.kind == "rod"]
    assert {round(s.start_m[2], 6) for s in rods} >= {-0.5, -1.5}
    assert not any(min(s.start_m[2], s.end_m[2]) < -1.5 < max(s.start_m[2], s.end_m[2]) for s in rods)


def test_missing_inputs_for_calculation():
    assert missing_for_calculation({"soil_layers": [], "fault": {"current_a": None}}) == [
        "geometry", "soil_layers", "fault.current_a", "fault.clearing_time_s"]
    assert missing_for_calculation({"geometry": REGULAR, "soil_layers": [{"resistivity_ohm_m": 100}],
                                    "fault": {"current_a": 1, "clearing_time_s": 0.5}}) == []


def test_clip_zone_keeps_the_left_grid_and_the_zone_outline():
    from src.domain.spat.grid_geometry import clip_conductors, explicit_conductors

    geometry = {"length_m": 40, "width_m": 30, "conductor_spacing_x_m": 4, "conductor_spacing_y_m": 6}
    clipped = clip_conductors(explicit_conductors(geometry), 20, 40, 0, 30)
    lines = {((c["start"]["x"], c["start"]["y"]), (c["end"]["x"], c["end"]["y"])) for c in clipped}
    assert ((0.0, 12.0), (20.0, 12.0)) in lines  # interior horizontals stop at the zone border
    assert ((0.0, 0.0), (40.0, 0.0)) in lines and ((0.0, 30.0), (40.0, 30.0)) in lines  # outline stays
    assert ((20.0, 0.0), (20.0, 30.0)) in lines and ((40.0, 0.0), (40.0, 30.0)) in lines
    assert not any(20 < a[0] < 40 and a[0] == b[0] for a, b in lines)  # no verticals inside the zone
    assert ((4.0, 0.0), (4.0, 30.0)) in lines  # left side untouched
    assert geometry_problems({**geometry, "conductors": clipped}) == []


def test_exact_rod_count_on_junctions():
    geometry = {"length_m": 40, "width_m": 10, "conductor_spacing_x_m": 5, "conductor_spacing_y_m": 2}
    rods = rod_layout("count", geometry, count=45)
    assert len(rods) == 45 and len({(r["x"], r["y"]) for r in rods}) == 45
    assert {(0.0, 0.0), (40.0, 0.0), (40.0, 10.0), (0.0, 10.0)} <= {(r["x"], r["y"]) for r in rods}
    assert geometry_problems({**geometry, "rods": rods}) == []
    assert len(rod_layout("count", geometry, count=4)) == 4
    with pytest.raises(ValueError, match="only 54 conductor junctions"):
        rod_layout("count", geometry, count=60)
