import pytest

from src.domain.spat.grid_geometry import (
    area_grid, axis_positions, geometry_conflicts, geometry_warnings, snapped_positions, conductor_lines, geometry_problems, missing_for_calculation, rod_layout, rod_points, split_lines,
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


def test_structures_are_obstacles_for_conductors_and_rods():
    geometry = {"length_m": 40, "width_m": 30, "conductors": [
        {"start": {"x": 0, "y": 15}, "end": {"x": 40, "y": 15}},
    ], "rods": [{"x": 0, "y": 15}], "structures": [
        {"x": 20, "y": 15, "width": 10, "height": 6, "label": "Casa"},
    ]}
    problems = geometry_problems(geometry)
    assert any("crosses structure [0]" in problem for problem in problems)

    geometry["conductors"][0] = {"start": {"x": 0, "y": 12}, "end": {"x": 40, "y": 12}}
    geometry["rods"] = [{"x": 0, "y": 12}]
    assert geometry_problems(geometry) == []


def test_structure_must_stay_inside_grid():
    geometry = {"length_m": 40, "width_m": 30, "conductor_spacing_m": 10,
                "structures": [{"x": 39, "y": 15, "width": 6, "height": 4}]}
    assert any("structures[0] leaves" in problem for problem in geometry_problems(geometry))


# Antejardín 2 × 10 m, existing building 20 × 10 m and back yard 5 × 10 m on a 27 × 10 m site.
SITE = {"length_m": 27, "width_m": 10,
        "structures": [{"x": 12, "y": 5, "width": 20, "height": 10, "label": "Edificio existente"}],
        "areas": [{"type": "intervenible", "label": "Antejardín", "x_min": 0, "x_max": 2, "y_min": 0, "y_max": 10},
                  {"type": "intervenible", "label": "Patio", "x_min": 22, "x_max": 27, "y_min": 0, "y_max": 10}]}


def test_the_grid_uses_the_chosen_area_not_every_available_one():
    with pytest.raises(ValueError, match="2 intervenible areas .*say which one"):
        area_grid(SITE, 5, 5)
    conductors = area_grid(SITE, 5, 5, areas=["patio"])
    xs = {c[k]["x"] for c in conductors for k in ("start", "end")}
    assert xs == {22, 27} and len(conductors) == 3 + 2  # y = 0, 5, 10 and the patio's two sides
    geometry = {**SITE, "conductors": conductors}
    geometry["rods"] = rod_layout("count", geometry, count=4)
    assert geometry_problems(geometry) == [] and geometry_warnings(geometry) == []
    # Part of the patio only, with the interior lines on the construction step.
    part = area_grid({**SITE, "snap_m": 1}, 3, 3, areas=["Patio"], bounds={"x_min": 22, "x_max": 27, "y_min": 0, "y_max": 6})
    ys = sorted({c["start"]["y"] for c in part if c["start"]["y"] == c["end"]["y"]})
    xs = sorted({c["start"]["x"] for c in part if c["start"]["x"] == c["end"]["x"]})
    assert ys == [0, 3, 6] and xs == [22, 25, 27]  # 24.5 rounds up to 25: gaps of 3 and 2 m


def test_snapped_positions_never_exceed_the_spacing():
    assert snapped_positions(0, 5, 3, 0.5) == [0, 2.5, 5]
    assert snapped_positions(0, 5, 3, 1) == [0, 3, 5]  # halves round up
    for start, end, spacing, snap in ((0, 7, 2, 1), (2.3, 11.9, 3, 0.5), (0, 10, 4, 3)):
        points = snapped_positions(start, end, spacing, snap)
        assert points[0] == start and points[-1] == end
        assert all(b - a <= spacing + 1e-3 for a, b in zip(points, points[1:]))


def test_two_used_areas_are_a_warning_not_an_error():
    both = {**SITE, "conductors": area_grid(SITE, 5, 5, areas=["Antejardín", "Patio"])}
    assert geometry_problems(both) == []
    [warning] = geometry_warnings(both)
    assert warning["kind"] == "disconnected" and warning["parts"] == 2


def test_conflicts_are_structured():
    across = {**SITE, "conductors": [{"start": {"x": 0, "y": 5}, "end": {"x": 27, "y": 5}}]}
    crossing = [c for c in geometry_conflicts(across) if c["kind"] == "crosses_obstacle"]
    assert crossing == [{"element": "conductor", "index": 0, "kind": "crosses_obstacle",
                         "message": "geometry.conductors[0] crosses structure [0]",
                         "obstacle": {"kind": "structure", "index": 0, "label": "Edificio existente"}, "other": None}]


def test_conductors_and_rods_must_stay_in_the_intervenible_areas():
    assert any("regular grid covers the whole site" in p for p in geometry_problems({**SITE, "conductor_spacing_m": 5}))
    across = {**SITE, "conductors": [{"start": {"x": 0, "y": 5}, "end": {"x": 27, "y": 5}}], "rods": [{"x": 10, "y": 5}]}
    problems = geometry_problems(across)
    assert any("crosses structure [0]" in p for p in problems)
    assert any("conductors[0] leaves the intervenible areas" in p for p in problems)
    assert any("rods[0] at (10, 5) is outside the intervenible areas" in p for p in problems)
    assert any("rods[0] is inside structure [0]" in p for p in problems)
    # Along the shared border the conductor is still inside the area.
    border = {**SITE, "conductors": [{"start": {"x": 2, "y": 0}, "end": {"x": 2, "y": 10}}]}
    assert geometry_problems(border) == []


def test_non_intervenible_areas_block_the_grid_and_areas_stay_in_the_site():
    garden = {"type": "non_intervenible", "label": "Jardín", "x_min": 23, "x_max": 25, "y_min": 4, "y_max": 6}
    geometry = {**SITE, "areas": [*SITE["areas"], garden],
                "conductors": [{"start": {"x": 22, "y": 5}, "end": {"x": 27, "y": 5}}]}
    assert any("crosses non-intervenible area [2] (Jardín)" in p for p in geometry_problems(geometry))
    clipped = area_grid(geometry, 5, 5, areas=["Patio"])
    assert geometry_problems({**geometry, "conductors": clipped}) == []
    outside = {**SITE, "conductors": [{"start": {"x": 0, "y": 0}, "end": {"x": 2, "y": 0}}],
               "areas": [{"type": "intervenible", "x_min": 20, "x_max": 30, "y_min": 0, "y_max": 10}]}
    assert geometry_problems(outside) == ["geometry.areas[0] leaves the site (0..27 x 0..10 m)"]


# ---- SV-28: rods of different lengths in one network -------------------------------------------------------------

MIXED_RODS = {"length_m": 20, "width_m": 20, "burial_depth_m": 0.5, "rod_length_m": 2.4, "conductors": [
    {"start": {"x": 0, "y": 0}, "end": {"x": 20, "y": 0}}, {"start": {"x": 0, "y": 20}, "end": {"x": 20, "y": 20}},
    {"start": {"x": 0, "y": 0}, "end": {"x": 0, "y": 20}}, {"start": {"x": 20, "y": 0}, "end": {"x": 20, "y": 20}},
], "rods": [{"x": 0, "y": 0, "length_m": 1.0}, {"x": 20, "y": 0, "length_m": 3.0},
            {"x": 0, "y": 20, "length_m": None}, {"x": 20, "y": 20}]}


def test_rod_points_use_each_rods_own_length_and_inherit_the_default_otherwise():
    assert rod_points(MIXED_RODS) == [(0, 0, 1.0), (20, 0, 3.0), (0, 20, 2.4), (20, 20, 2.4)]
    assert rod_points({**MIXED_RODS, "rod_length_m": None})[2:] == [(0, 20, 2.4), (20, 20, 2.4)]  # built-in default
    assert geometry_problems(MIXED_RODS) == []


@pytest.mark.parametrize("rods, expected", [
    ([{"x": 0, "y": 0, "length_m": 0}], {("rod", 0, "length")}),
    ([{"x": 0, "y": 0, "length_m": -2.4}, {"x": 20, "y": 0, "length_m": "3"}], {("rod", 0, "length"), ("rod", 1, "length")}),
    ([{"x": 0, "y": 0, "length_m": float("inf")}], {("rod", 0, "length")}),
    ([{"x": 0, "y": 0, "length_m": True}], {("rod", 0, "length")}),
])
def test_rod_lengths_must_be_positive_finite_numbers(rods, expected):
    conflicts = geometry_conflicts({**MIXED_RODS, "rods": rods})
    assert {(c["element"], c["index"], c["kind"]) for c in conflicts} == expected
    assert all("positive number" in c["message"] for c in conflicts)


def test_rods_that_inherit_an_unusable_default_length_are_reported():
    inherited = geometry_conflicts({**MIXED_RODS, "rod_length_m": -1})
    assert [(c["element"], c["index"], c["kind"]) for c in inherited] == [("rod", 2, "length"), ("rod", 3, "length")]
    regular = geometry_conflicts({**REGULAR, "rod_length_m": 0})
    assert [(c["element"], c["kind"]) for c in regular] == [("geometry", "rod_length")]
    assert geometry_problems({**REGULAR, "rods_count": 0, "rod_length_m": 0}) == []  # no rods: the default is unused


def _rod_lengths_by_position(segments):
    """Plan position -> total length of the rod pieces the solver receives there."""
    totals: dict[tuple[float, float], float] = {}
    for s in segments:
        if s.kind == "rod":
            key = (round(s.start_m[0], 6), round(s.start_m[1], 6))
            totals[key] = totals.get(key, 0.0) + abs(s.start_m[2] - s.end_m[2])
    return {key: round(value, 6) for key, value in totals.items()}


@pytest.mark.parametrize("segmentation", ["uniform", "graded"])
def test_every_rod_reaches_the_solver_with_its_own_length(segmentation):
    parameters = {"discretization_m": 1.0, "conductor_radius_m": 0.005, "segmentation": segmentation}
    segments = _segments(MIXED_RODS, parameters, HomogeneousSoil(100.0))
    # The network is centred on the outline, so the plan positions are shifted by half the site.
    assert _rod_lengths_by_position(segments) == {(-10.0, -10.0): 1.0, (10.0, -10.0): 3.0, (-10.0, 10.0): 2.4, (10.0, 10.0): 2.4}
    tops = {(round(s.start_m[0], 6), round(s.start_m[1], 6)) for s in segments if s.kind == "rod"}
    assert all(any(abs(s.start_m[2] + 0.5) < 1e-9 for s in segments if s.kind == "rod" and
                   (round(s.start_m[0], 6), round(s.start_m[1], 6)) == top) for top in tops)  # every rod starts at the grid


def test_only_the_rods_that_cross_a_soil_interface_are_cut_there():
    soil = TwoLayerSoil(300.0, 100.0, 2.0)  # interface at z = -2.0: the 1.0 m rod ends at -1.5, the others go through
    segments = _segments(MIXED_RODS, {"discretization_m": 1.0, "conductor_radius_m": 0.005, "segmentation": "graded"}, soil)
    assert _rod_lengths_by_position(segments) == {(-10.0, -10.0): 1.0, (10.0, -10.0): 3.0, (-10.0, 10.0): 2.4, (10.0, 10.0): 2.4}
    rods = [s for s in segments if s.kind == "rod"]
    at_interface = {(round(s.start_m[0], 6), round(s.start_m[1], 6)) for s in rods
                    if any(abs(z + 2.0) < 1e-9 for z in (s.start_m[2], s.end_m[2]))}
    assert at_interface == {(10.0, -10.0), (-10.0, 10.0), (10.0, 10.0)}
    assert not any(min(s.start_m[2], s.end_m[2]) < -2.0 < max(s.start_m[2], s.end_m[2]) for s in rods)
    short = [s for s in rods if (round(s.start_m[0], 6), round(s.start_m[1], 6)) == (-10.0, -10.0)]
    assert min(min(s.start_m[2], s.end_m[2]) for s in short) == pytest.approx(-1.5)


def test_two_rods_at_the_same_point_are_a_plan_error():
    from src.domain.spat.grid_geometry import unique_rods
    rods = [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 0.0, "y": 0.0004}]
    [conflict] = [c for c in geometry_conflicts({**REGULAR, "rods": rods}) if c["kind"] == "duplicate"]
    assert (conflict["element"], conflict["index"], conflict["other"]) == ("rod", 2, 0)
    assert unique_rods(rods) == ([{"x": 0, "y": 0}, {"x": 10, "y": 0}], 1)
