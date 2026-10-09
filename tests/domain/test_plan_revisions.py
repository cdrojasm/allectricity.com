from src.domain.spat.plan_revisions import compare_plan_revisions


def test_plan_revision_reports_obstacle_changes_and_new_conflicts():
    old = {"length_m": 20, "width_m": 20, "conductor_spacing_m": 10,
           "structures": [{"x": 5, "y": 5, "width": 4, "height": 4, "label": "Casa"}]}
    new = {"length_m": 20, "width_m": 20, "conductors": [
               {"start": {"x": 0, "y": 5}, "end": {"x": 20, "y": 5}}],
           "structures": [{"x": 10, "y": 5, "width": 4, "height": 4, "label": "Casa"},
                          {"x": 4, "y": 15, "width": 2, "height": 2, "label": "Vía"}]}
    result = compare_plan_revisions(old, new)
    assert result["added"] == [{"x": 4, "y": 15, "width": 2, "height": 2, "label": "Vía"}]
    assert result["changed"][0]["before"]["x"] == 5
    assert result["has_conflicts"] is True


def test_plan_revision_reports_a_grid_outside_the_intervenible_areas():
    site = {"length_m": 27, "width_m": 10, "conductors": [{"start": {"x": 0, "y": 0}, "end": {"x": 27, "y": 0}}],
            "areas": [{"type": "intervenible", "x_min": 0, "x_max": 2, "y_min": 0, "y_max": 10}]}
    result = compare_plan_revisions({}, site)
    assert result["has_conflicts"] and "leaves the intervenible areas" in result["conflicts"][0]
