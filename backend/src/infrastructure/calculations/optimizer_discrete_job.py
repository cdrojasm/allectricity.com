"""Worker side of the discrete optimizer run (OP-06/OP-19): the API validates, stores a queued run
and dispatches; this evaluates the candidates and stores the alternatives. No web framework here."""

from __future__ import annotations

from time import time
from typing import Any
from uuid import uuid4

from src.application.use_cases.optimizer_run import run_discrete_optimizer
from src.domain.spat.artifact_contract import validate_artifact
from src.infrastructure.calculations import safety_criteria
from src.infrastructure.calculations.potential_engine_client import (HomogeneousSoil, LayerStackSoil,
                                                                     PotentialEngineClient, TwoLayerSoil)
from src.infrastructure.persistence.optimizer_run_repository import OptimizerRunRepository


def soil_model(soil: dict[str, Any]):
    if soil["model"] == "homogeneous":
        return HomogeneousSoil(soil["resistivity_ohm_m"])
    if soil["model"] == "two-layer":
        return TwoLayerSoil(soil["upper_resistivity_ohm_m"], soil["lower_resistivity_ohm_m"], soil["upper_thickness_m"])
    return LayerStackSoil(tuple((layer["resistivity_ohm_m"], layer.get("thickness_m")) for layer in soil["layers"]),
                          soil.get("kernel_density"))


def top_resistivity(soil: dict[str, Any]) -> float:
    if soil["model"] == "homogeneous":
        return soil["resistivity_ohm_m"]
    if soil["model"] == "two-layer":
        return soil["upper_resistivity_ohm_m"]
    return soil["layers"][0]["resistivity_ohm_m"]


def _alternatives(result: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    alternatives = []
    for rank, candidate in enumerate(result.get("feasible_candidates", []), start=1):
        evaluation = candidate.get("safety") or {}
        evaluation_snapshot = {
            "feasible": evaluation.get("Feasible") is True,
            "feasibility_status": evaluation.get("FeasibilityStatus"),
            "certified": (evaluation.get("FeasibilityBasis") or {}).get("certified") is True,
            "cost": candidate.get("cost"),
            "cost_detail": candidate.get("cost_detail") or {},
            "safety": evaluation,
            "geometry": evaluation.get("geometry"),
            "trace": {
                "candidate_sha256": candidate.get("candidate_sha256"),
                "selected_discrete_options": evaluation.get("SelectedDiscreteOptions"),
                "solver_input_sha256": evaluation.get("SolverInputSha256"),
                "constraint_context_schema_version": context.get("schema_version"),
                "site_geometry_sha256": context.get("site_geometry_sha256"),
            },
        }
        alternatives.append({
            "id": str(uuid4()), "candidate_sha256": candidate["candidate_sha256"],
            "rank": rank, "recommended": rank == 1,
            "candidate_snapshot": candidate["parameters"],
            "evaluation_snapshot": evaluation_snapshot,
            "created_at": int(time()),
        })
    return alternatives


SUMMARY_KEYS = ("algorithm", "seed", "max_evaluations", "unique_evaluations", "solver_evaluations",
                "budget_exhausted", "restarts_requested", "restarts_started", "restart_summaries",
                "best", "diagnostics", "cost_policy", "cost_currency")


def execute_discrete_run(store, run_id: str, client_factory=PotentialEngineClient) -> str:
    """Run one queued discrete run to a terminal state; a redelivered or cancelled run is left alone."""
    with store.transaction(write=True) as db:
        repo = OptimizerRunRepository(db.connection)
        run = repo.get_run_by_id(run_id)
        if run is None:
            return "missing"
        project_id = run["project_id"]
        if repo.transition(project_id, run_id, ("queued",), {"status": "running", "updated_at": int(time())}) is None:
            return run["status"]
        artifact_row = db.designs.get_version(project_id, run["artifact_id"], run["artifact_version"])
    snapshot = run["request_snapshot"]
    payload, context, inputs = snapshot["request"], snapshot["constraint_context"], snapshot["worker_inputs"]
    try:
        if not artifact_row:
            raise ValueError("The run's artifact version no longer exists")
        geometry = validate_artifact(artifact_row["snapshot"])["geometry"]
        exposure_input = payload["exposure"]
        exposure = safety_criteria.FaultExposure(
            clearing_time_s=exposure_input["clearing_time_s"],
            body_weight_kg=exposure_input["body_weight_kg"],
            surface_resistivity_ohm_m=exposure_input["surface_resistivity_ohm_m"],
            surface_thickness_m=exposure_input["surface_thickness_m"],
            soil_resistivity_ohm_m=top_resistivity(payload["soil"]),
            exposure_class=exposure_input["exposure_class"],
            surface_layer_present=exposure_input["surface_layer_present"],
        )
        result = run_discrete_optimizer(
            base_parameters=inputs["base_parameters"],
            base_geometry=geometry,
            constraint_context=context,
            optimized_variables=payload["variables"],
            soil=soil_model(payload["soil"]),
            injection_a=payload["injection_a"],
            points=[],  # OP-04 derives its safety search points from each candidate geometry.
            client=client_factory(),
            exposure=exposure,
            standards=payload["standards"],
            explicit_quantities=inputs["quantities"],
            cost_currency=payload["cost_currency"],
            seed=payload["seed"],
            max_evaluations=payload["max_evaluations"],
            restarts=payload["restarts"],
        )
        with store.transaction(write=True) as db:
            repo = OptimizerRunRepository(db.connection)
            if repo.transition(project_id, run_id, ("running",), {
                    "status": "completed", "result_summary": {key: result.get(key) for key in SUMMARY_KEYS},
                    "error": None, "updated_at": int(time())}) is None:
                return repo.get_run(project_id, run_id)["status"]  # cancelled meanwhile: keep no alternatives
            repo.add_alternatives(project_id, run_id, _alternatives(result, context))
        return "completed"
    except Exception as exc:
        with store.transaction(write=True) as db:
            OptimizerRunRepository(db.connection).transition(project_id, run_id, ("running",), {
                "status": "failed", "error": str(exc)[:2000], "updated_at": int(time())})
        if isinstance(exc, (ValueError, TypeError)):
            return "failed"
        raise
