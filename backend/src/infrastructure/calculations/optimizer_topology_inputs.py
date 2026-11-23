"""Turn a stored topology-run request snapshot into `run_topology_optimizer` arguments.

The API writes the snapshot once (request, resolved OP-05 context, rate card and site); the worker rebuilds the
same arguments from it, so a run resumed after a restart solves exactly the problem that was queued.
"""

from __future__ import annotations

import os
from typing import Any

from src.application.use_cases.optimizer_topology_job import TOPOLOGY_STRATEGY
from src.domain.spat.geometry_operators import OperatorConstraints, bridges_of, diagonals_of
from src.infrastructure.calculations import safety_criteria
from src.infrastructure.calculations.potential_engine_client import HomogeneousSoil, LayerStackSoil, TwoLayerSoil


def soil_model(value: dict[str, Any]):
    if value["model"] == "homogeneous":
        return HomogeneousSoil(value["resistivity_ohm_m"])
    if value["model"] == "two-layer":
        return TwoLayerSoil(value["upper_resistivity_ohm_m"], value["lower_resistivity_ohm_m"], value["upper_thickness_m"])
    return LayerStackSoil(tuple((layer["resistivity_ohm_m"], layer.get("thickness_m")) for layer in value["layers"]),
                          value.get("kernel_density", 10))


def top_resistivity(value: dict[str, Any]) -> float:
    if value["model"] == "homogeneous":
        return value["resistivity_ohm_m"]
    if value["model"] == "two-layer":
        return value["upper_resistivity_ohm_m"]
    return value["layers"][0]["resistivity_ohm_m"]


def exposure(request: dict[str, Any]) -> safety_criteria.FaultExposure:
    data = request["exposure"]
    return safety_criteria.FaultExposure(
        clearing_time_s=data["clearing_time_s"], body_weight_kg=data["body_weight_kg"],
        surface_resistivity_ohm_m=data["surface_resistivity_ohm_m"], surface_thickness_m=data["surface_thickness_m"],
        soil_resistivity_ohm_m=top_resistivity(request["soil"]), exposure_class=data.get("exposure_class"),
        surface_layer_present=data["surface_layer_present"])


def parallel_workers() -> int:
    try:
        return max(1, min(8, int(os.getenv("OPTIMIZER_PARALLEL_WORKERS", "1"))))
    except ValueError:
        return 1


def build_inputs(snapshot: dict[str, Any]) -> dict[str, Any]:
    request = snapshot["request"]
    applied = snapshot["operator_constraints"]
    limits = applied["rod_length_range_m"]
    redundant = bool(applied.get("redundant"))          # runs from before the rule have no key: they replay unconstrained
    return {
        "domain": snapshot["site"], "initial_geometry": snapshot["initial_geometry"],
        "rate_card": snapshot["rate_card"], "soil": soil_model(request["soil"]), "injection_a": request["injection_a"],
        "exposure": exposure(request), "standards": request["standards"], "seed": request["seed"],
        "max_solver_calls": request["max_solver_calls"], "seed_count": request["seed_count"],
        "strategy": TOPOLOGY_STRATEGY, "constraints": OperatorConstraints(
            rod_length_range_m=(limits["min"], limits["max"]), orthogonal=bool(snapshot["operator_constraints"].get("orthogonal")),
            inherited_diagonals=diagonals_of(snapshot["initial_geometry"]) if snapshot["operator_constraints"].get("orthogonal") else (),
            redundant=redundant, inherited_bridges=bridges_of(snapshot["initial_geometry"]) if redundant else (),
            **({"stub_max_m": float(applied["stub_max_m"]["value"])} if redundant and applied.get("stub_max_m") else {})),
        "constraint_context": snapshot["constraint_context"], "parallel_workers": snapshot.get("parallel_workers", 1),
        "settings": snapshot.get("settings"),
    }


def evaluate_base(inputs: dict[str, Any], client: Any) -> dict[str, Any]:
    """The starting design's verdict at the finest level, so the comparison can say whether it complies.

    One solver call outside the search budget. A geometry the solver refuses is reported, never treated as a pass.
    """
    from src.application.use_cases.optimizer_topology_run import electrical_verdict
    from src.domain.spat.optimizer_constraints import OptimizerGeometryRejected
    from src.infrastructure.calculations import optimizer_evaluation

    try:
        result = optimizer_evaluation.evaluate_design(
            design_parameters=None, base_geometry=inputs["initial_geometry"], soil=inputs["soil"],
            injection_a=inputs["injection_a"], points=[], client=client, exposure=inputs["exposure"],
            standards=inputs["standards"], settings=inputs.get("settings"), level="L3",
            constraint_context=inputs["constraint_context"])
    except OptimizerGeometryRejected as rejected:
        return {"status": "REJECTED", "reason": "geometry_rejected", "detail": str(rejected)[:500], "level": "L3"}
    return {**electrical_verdict("L3", result), "level": "L3"}
