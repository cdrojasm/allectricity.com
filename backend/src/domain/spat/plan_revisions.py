"""Deterministic comparison helpers for construction-plan revisions."""

from src.domain.spat.grid_geometry import geometry_conflicts

# Conflicts between the grid and the site's obstacles and zones (not plain drawing errors).
SITE_CONFLICTS = {"crosses_obstacle", "inside_obstacle", "outside_areas", "regular_grid_over_areas"}


def _key(item: dict, index: int) -> str:
    return str(item.get("label") or f"{item.get('type', 'structure')}:{index}").casefold()


def compare_plan_revisions(previous: dict, current: dict) -> dict:
    """Compare obstacle revisions and report conflicts with the current conductors."""
    old = previous or {}
    new = current or {}
    old_structures = {_key(item, i): item for i, item in enumerate(old.get("structures") or [])}
    new_structures = {_key(item, i): item for i, item in enumerate(new.get("structures") or [])}
    added = [new_structures[key] for key in sorted(new_structures.keys() - old_structures.keys())]
    removed = [old_structures[key] for key in sorted(old_structures.keys() - new_structures.keys())]
    changed = [{"before": old_structures[key], "after": new_structures[key]}
               for key in sorted(old_structures.keys() & new_structures.keys())
               if old_structures[key] != new_structures[key]]
    conflicts = [conflict["message"] for conflict in geometry_conflicts({**new, "structures": new.get("structures") or []})
                 if conflict["kind"] in SITE_CONFLICTS]
    return {"added": added, "removed": removed, "changed": changed,
            "conflicts": conflicts, "has_conflicts": bool(conflicts)}
