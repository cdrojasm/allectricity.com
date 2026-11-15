"""Project-scoped optimizer runs: the synchronous discrete search (OP-06/OP-19) and the queued topological search."""

from __future__ import annotations

import hashlib
import json
import os
from time import time
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.application.use_cases import potential_calculations
from src.application.use_cases.optimizer_run import run_discrete_optimizer
from src.domain.spat.artifact_contract import validate_artifact
from src.infrastructure.calculations import artifact_potential, safety_criteria
from src.infrastructure.calculations.conductor_thermal import equivalent_radius_m
from src.infrastructure.calculations.potential_engine_client import (
    HomogeneousSoil,
    LayerStackSoil,
    PotentialEngineClient,
    TwoLayerSoil,
    soil_record,
)
from src.infrastructure.entrypoint.api.constraint_profile_routes import (
    _attach_site_domain,
    _owned_project,
    _selected_context,
)
from src.infrastructure.entrypoint.api.schemas import PotentialCalculationRequest
from src.infrastructure.entrypoint.worker.tasks import calculate_artifact_potential
from src.infrastructure.persistence.constraint_profile_repository import ConstraintProfileRepository
from src.infrastructure.persistence.material_catalog_repository import MaterialCatalogRepository
from src.infrastructure.persistence.optimizer_run_repository import OptimizerRunRepository
from src.infrastructure.security.middleware import require
from src.infrastructure.services.optimizer_material_options import approved_material_domains
from src.domain.spat.discrete_domains import resolve_discrete_domains


router = APIRouter(prefix="/api/v1/projects/{project_id}/optimizer-runs", tags=["optimizer"])


@router.get("")
def list_optimizer_runs(project_id: str, request: Request,
                        limit: int = Query(default=50, ge=1, le=100),
                        actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        _owned_project(db, project_id, actor)
        rows = OptimizerRunRepository(db.connection).list_runs(project_id, limit=limit)
    return {"runs": rows}


@router.get("/rate-options")
def rate_options(project_id: str, request: Request, currency: str = Query(pattern=r"^[A-Z]{3}$"),
                 actor=Depends(require("designs:read"))):
    """Approved catalog items the project can price each cost line with, in the run currency."""
    from src.application.use_cases import optimizer_topology_job as job

    with request.app.state.services.store.transaction() as db:
        _owned_project(db, project_id, actor)
        rows = MaterialCatalogRepository(db.connection).list(project_id, "approved")
    return {"currency": currency, "options": job.catalog_rate_options(rows, currency=currency, now_epoch_s=int(time()))}


@router.get("/{run_id}")
def get_optimizer_run(project_id: str, run_id: str, request: Request,
                      actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        _owned_project(db, project_id, actor)
        repo = OptimizerRunRepository(db.connection)
        run = repo.get_run(project_id, run_id)
        if not run:
            raise HTTPException(404, "Optimizer run not found")
        alternatives = repo.list_alternatives(project_id, run_id)
    return {"run": run, "alternatives": alternatives}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HomogeneousSoilInput(StrictModel):
    model: Literal["homogeneous"]
    resistivity_ohm_m: float = Field(gt=0, le=1_000_000)


class TwoLayerSoilInput(StrictModel):
    model: Literal["two-layer"]
    upper_resistivity_ohm_m: float = Field(gt=0, le=1_000_000)
    lower_resistivity_ohm_m: float = Field(gt=0, le=1_000_000)
    upper_thickness_m: float = Field(ge=0.01, le=1000)


class SoilLayerInput(StrictModel):
    resistivity_ohm_m: float = Field(gt=0, le=1_000_000)
    thickness_m: float | None = Field(default=None, gt=0, le=1000)


class LayerStackSoilInput(StrictModel):
    model: Literal["n-layer"]
    layers: list[SoilLayerInput] = Field(min_length=1, max_length=8)
    kernel_density: int = Field(default=10, ge=6, le=12)

    @model_validator(mode="after")
    def valid_layer_stack(self):
        if any(layer.thickness_m is None for layer in self.layers[:-1]):
            raise ValueError("only the bottom soil layer may have null thickness")
        if self.layers[-1].thickness_m is not None:
            raise ValueError("the bottom soil layer must be a half-space with null thickness")
        return self


SoilInput = Annotated[
    HomogeneousSoilInput | TwoLayerSoilInput | LayerStackSoilInput,
    Field(discriminator="model"),
]


class ExposureInput(StrictModel):
    clearing_time_s: float = Field(gt=0, le=1000)
    body_weight_kg: float = Field(ge=50, le=70)
    surface_resistivity_ohm_m: float = Field(gt=0, le=1_000_000)
    surface_thickness_m: float = Field(ge=0, le=10)
    exposure_class: Literal["public", "occupational"] | None = None
    surface_layer_present: bool


class ApplicabilityFacts(StrictModel):
    """Flat, explicit applicability facts; project-owned country/type are server supplied."""

    values: dict[str, Any] = Field(default_factory=dict, max_length=100)

    @model_validator(mode="after")
    def facts_are_scalars(self):
        for key, value in self.values.items():
            if not isinstance(key, str) or not key.strip() or len(key) > 100:
                raise ValueError("applicability fact keys must be nonempty strings up to 100 characters")
            values = value if isinstance(value, list) else [value]
            if isinstance(value, (dict, list)) and not isinstance(value, list):
                raise ValueError(f"applicability fact {key!r} must be a scalar or scalar list")
            if not values or any(item is None or isinstance(item, (dict, list))
                                 or not isinstance(item, (str, int, float, bool))
                                 for item in values):
                raise ValueError(f"applicability fact {key!r} must contain scalar values")
        return self


class ExplicitQuantity(StrictModel):
    option_id: str = Field(min_length=1, max_length=240)
    value: float = Field(ge=0, le=1_000_000_000)
    unit: str = Field(min_length=1, max_length=40)


class OptimizerRunRequest(StrictModel):
    artifact_id: str = Field(min_length=36, max_length=36)
    artifact_version: int = Field(ge=1)
    soil: SoilInput
    injection_a: float = Field(gt=0, le=1_000_000)
    exposure: ExposureInput
    standards: list[str] = Field(min_length=1, max_length=5)
    variables: list[str] = Field(min_length=1, max_length=12)
    applicability_facts: ApplicabilityFacts = Field(default_factory=ApplicabilityFacts)
    quantities: list[ExplicitQuantity] = Field(min_length=1, max_length=1000)
    cost_policy: Literal["single_currency_only"]
    cost_currency: str = Field(pattern=r"^[A-Z]{3}$")
    seed: int = Field(ge=0, le=2_147_483_647)
    max_evaluations: int = Field(default=5, ge=1, le=5)
    restarts: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def unique_items(self):
        if len(set(self.variables)) != len(self.variables):
            raise ValueError("variables must not contain duplicates")
        if any(not value.strip() or len(value) > 240 for value in self.variables):
            raise ValueError("variables must be nonempty parameter paths up to 240 characters")
        if len(set(self.standards)) != len(self.standards):
            raise ValueError("standards must not contain duplicates")
        unknown = sorted(set(self.standards) - set(safety_criteria.SUPPORTED_STANDARDS))
        if unknown:
            raise ValueError("unsupported standards: " + ", ".join(unknown))
        option_ids = [item.option_id for item in self.quantities]
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("quantities must not contain duplicate option ids")
        return self


def _soil_model(value: SoilInput):
    if value.model == "homogeneous":
        return HomogeneousSoil(value.resistivity_ohm_m)
    if value.model == "two-layer":
        return TwoLayerSoil(value.upper_resistivity_ohm_m, value.lower_resistivity_ohm_m,
                            value.upper_thickness_m)
    return LayerStackSoil(tuple((layer.resistivity_ohm_m, layer.thickness_m)
                                for layer in value.layers), value.kernel_density)


def _top_resistivity(value: SoilInput) -> float:
    if value.model == "homogeneous":
        return value.resistivity_ohm_m
    if value.model == "two-layer":
        return value.upper_resistivity_ohm_m
    return value.layers[0].resistivity_ohm_m


def _base_parameters(geometry: dict[str, Any], variables: list[str], conductor: dict[str, Any]) -> dict[str, Any]:
    spacing_x = geometry.get("conductor_spacing_x_m") or geometry.get("conductor_spacing_m")
    spacing_y = geometry.get("conductor_spacing_y_m") or geometry.get("conductor_spacing_m")
    parameters: dict[str, Any] = {
        "burial_depth_m": geometry.get("burial_depth_m", 0.5),
        "conductor_radius_m": equivalent_radius_m(float(conductor["cross_section_mm2"])),
    }
    if geometry.get("conductors"):
        # A drawn plan's topology is fixed; only parameters accepted by OP-02 are exposed.
        parameters["translate_x_m"] = 0.0
        parameters["translate_y_m"] = 0.0
    else:
        if spacing_x is None or spacing_y is None:
            raise ValueError("regular artifact geometry must define spacing on both axes")
        parameters.update({
            "length_m": geometry["length_m"], "width_m": geometry["width_m"],
            "conductor_spacing_x_m": spacing_x, "conductor_spacing_y_m": spacing_y,
        })
    if any(path == "rod_length_m" for path in variables):
        parameters["rod_length_m"] = geometry.get("rod_length_m", 2.4)
    indexed_rod_variables = [path for path in variables if path.startswith("rod_lengths_m[")]
    if indexed_rod_variables:
        count = len(geometry.get("rods") or []) or int(geometry.get("rods_count") or 0)
        lengths = [float(rod.get("length_m", geometry.get("rod_length_m", 2.4)))
                   for rod in geometry.get("rods") or []]
        if not lengths:
            lengths = [float(geometry.get("rod_length_m", 2.4))] * count
        parameters["rod_lengths_m"] = lengths
    for key in ("perimeter_extension_m", "translate_x_m", "translate_y_m"):
        if any(path == key for path in variables):
            parameters.setdefault(key, 0.0)
    return parameters


@router.post("", status_code=201)
def create_optimizer_run(project_id: str, payload: OptimizerRunRequest, request: Request,
                         actor=Depends(require("designs:write"))):
    now = int(time())
    request_data = payload.model_dump(mode="json")
    quantities = {item.option_id: {"value": item.value, "unit": item.unit}
                  for item in payload.quantities}
    try:
        with request.app.state.services.store.transaction(write=True) as db:
            project = _owned_project(db, project_id, actor)
            artifact_row = db.designs.get_version(project_id, payload.artifact_id, payload.artifact_version)
            if not artifact_row:
                raise HTTPException(404, "Artifact version not found in this project")
            try:
                snapshot = validate_artifact(artifact_row["snapshot"])
            except ValueError as exc:
                raise HTTPException(422, f"Stored artifact is invalid: {exc}") from exc
            if snapshot.get("schema_version") != "1.0" or not snapshot.get("geometry"):
                raise HTTPException(422, "Optimizer currently supports version 1.0 artifacts with one grid geometry")
            geometry = snapshot["geometry"]
            base_parameters = _base_parameters(geometry, payload.variables, snapshot.get("conductor") or {})
            for variable in payload.variables:
                if variable == "rod_length_m" and "rod_length_m" not in base_parameters:
                    raise HTTPException(422, "rod_length_m is not a supported base parameter for this artifact")
                if variable.startswith("rod_lengths_m["):
                    try:
                        index = int(variable[len("rod_lengths_m["):-1])
                    except ValueError as exc:
                        raise HTTPException(422, f"Invalid indexed variable path: {variable}") from exc
                    if (not variable.endswith("]") or index < 0
                            or index >= len(base_parameters.get("rod_lengths_m", []))):
                        raise HTTPException(422, f"Variable {variable} does not identify a rod in this artifact")
            selected = ConstraintProfileRepository(db.connection).selected(project_id)
            if any(row["status"] != "reviewed" for row in selected):
                raise HTTPException(409, "A selected profile is no longer reviewed; select a reviewed version")
            context = _selected_context(project, selected, payload.variables)
            context = _attach_site_domain(context, geometry, payload.variables)
            facts = dict(payload.applicability_facts.values)
            facts["country"] = project.get("country")
            facts["installation_type"] = context.get("profile", {}).get("installation_type")
            catalog_rows = MaterialCatalogRepository(db.connection).list(project_id, "approved")
            catalog_domains = approved_material_domains(catalog_rows, now_epoch_s=now)
            context["applicability_facts"] = facts
            resolved = resolve_discrete_domains(catalog_domains, facts)
            context["discrete_domains"] = resolved
            context["discrete_optimizable_variables"] = sorted({
                domain["target"] for domain in resolved["domains"]
                if domain["status"] == "ready" and domain["candidate_values"]
            }) if context.get("status") == "ready" else []
            if context.get("status") != "ready":
                raise HTTPException(422, "OP-05 context is blocked: " + ", ".join(
                    context.get("missing_mandatory_criteria") or ["unknown constraint"]
                ))
            if not set(payload.variables).issubset(set(context["discrete_optimizable_variables"])):
                raise HTTPException(422, "Every optimized variable must have an applicable approved discrete domain")
            eligible_options = {
                option["option_id"]: option
                for domain in resolved["domains"] if domain["status"] == "ready"
                for option in domain["options"]
                if option["option_id"] in set(domain["candidate_option_ids"])
            }
            unknown_quantity_ids = sorted(set(quantities) - set(eligible_options))
            if unknown_quantity_ids:
                raise HTTPException(422, "Quantities reference options outside the resolved OP-05 candidate set")
            matching_currency_options = [
                option for option in eligible_options.values()
                if (option.get("provenance", {}).get("quote") or {}).get("currency") == payload.cost_currency
            ]
            if not matching_currency_options:
                raise HTTPException(422, "No resolved catalog option uses the requested cost currency")
            run_id = str(uuid4())
            request_snapshot = {
                "request": request_data,
                "constraint_context": context,
                "artifact_snapshot_sha256": hashlib.sha256(
                    json.dumps(snapshot, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
            }
            repo = OptimizerRunRepository(db.connection)
            repo.create_run({
                "id": run_id, "project_id": project_id, "artifact_id": payload.artifact_id,
                "artifact_version": payload.artifact_version, "status": "running",
                "request_snapshot": request_snapshot, "result_summary": None, "error": None,
                "created_by": actor.user_id, "created_at": now, "updated_at": now,
            })
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    try:
        exposure = safety_criteria.FaultExposure(
            clearing_time_s=payload.exposure.clearing_time_s,
            body_weight_kg=payload.exposure.body_weight_kg,
            surface_resistivity_ohm_m=payload.exposure.surface_resistivity_ohm_m,
            surface_thickness_m=payload.exposure.surface_thickness_m,
            soil_resistivity_ohm_m=_top_resistivity(payload.soil),
            exposure_class=payload.exposure.exposure_class,
            surface_layer_present=payload.exposure.surface_layer_present,
        )
        result = run_discrete_optimizer(
            base_parameters=base_parameters,
            base_geometry=geometry,
            constraint_context=context,
            optimized_variables=payload.variables,
            soil=_soil_model(payload.soil),
            injection_a=payload.injection_a,
            points=[],  # OP-04 derives its safety search points from each candidate geometry.
            client=PotentialEngineClient(),
            exposure=exposure,
            standards=payload.standards,
            explicit_quantities=quantities,
            cost_currency=payload.cost_currency,
            seed=payload.seed,
            max_evaluations=payload.max_evaluations,
            restarts=payload.restarts,
        )
        alternatives = []
        for rank, candidate in enumerate(result.get("feasible_candidates", []), start=1):
            cost_detail = candidate.get("cost_detail") or {}
            evaluation = candidate.get("safety") or {}
            evaluation_snapshot = {
                "feasible": evaluation.get("Feasible") is True,
                "feasibility_status": evaluation.get("FeasibilityStatus"),
                "certified": (evaluation.get("FeasibilityBasis") or {}).get("certified") is True,
                "cost": candidate.get("cost"),
                "cost_detail": cost_detail,
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
        result_summary = {key: result.get(key) for key in (
            "algorithm", "seed", "max_evaluations", "unique_evaluations", "solver_evaluations",
            "budget_exhausted", "restarts_requested", "restarts_started", "restart_summaries",
            "best", "diagnostics", "cost_policy", "cost_currency",
        )}
        with request.app.state.services.store.transaction(write=True) as db:
            repo = OptimizerRunRepository(db.connection)
            saved = repo.add_alternatives(project_id, run_id, alternatives)
            run = repo.update_run(project_id, run_id, {
                "status": "completed", "result_summary": result_summary,
                "error": None, "updated_at": int(time()),
            })
        return {"run": run, "alternatives": saved}
    except Exception as exc:
        with request.app.state.services.store.transaction(write=True) as db:
            run = OptimizerRunRepository(db.connection).update_run(project_id, run_id, {
                "status": "failed", "error": str(exc)[:2000], "updated_at": int(time()),
            })
        if isinstance(exc, (ValueError, TypeError)):
            raise HTTPException(422, str(exc)) from exc
        raise HTTPException(502, "Optimizer run failed while evaluating candidates") from exc


# ---- topological optimizer (OPT-010…017 in the product): queued job, cancel, comparison, apply ------------------

from src.application.use_cases import optimizer_topology_job as topology_job  # noqa: E402
from src.domain.spat.geometry_cost import evaluate_geometry_cost  # noqa: E402
from src.infrastructure.calculations import optimizer_topology_inputs  # noqa: E402


class RateInput(StrictModel):
    """One rate: an approved catalog item, or an explicit amount with its source. Never both, never neither."""

    catalog_item_id: str | None = Field(default=None, min_length=36, max_length=36)
    amount: float | None = Field(default=None, ge=0, le=1_000_000_000_000)
    source: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def one_origin(self):
        if (self.catalog_item_id is None) == (self.amount is None):
            raise ValueError("a rate is either a catalog_item_id or an amount with its source")
        if self.amount is not None and not (self.source or "").strip():
            raise ValueError("an explicit amount needs its source")
        return self


class TopologyRunRequest(StrictModel):
    artifact_id: str = Field(min_length=36, max_length=36)
    artifact_version: int = Field(ge=1)
    injection_a: float = Field(gt=0, le=1_000_000)
    exposure: ExposureInput
    standards: list[str] = Field(min_length=1, max_length=5)
    applicability_facts: ApplicabilityFacts = Field(default_factory=ApplicabilityFacts)
    cost_currency: str = Field(pattern=r"^[A-Z]{3}$")
    rates: dict[str, RateInput] = Field(min_length=1, max_length=40)
    trench_width_m: float = Field(gt=0, le=5)
    trench_width_source: str = Field(min_length=1, max_length=500)
    seed: int = Field(ge=0, le=2_147_483_647)
    max_solver_calls: int = Field(default=150, ge=20, le=400)
    seed_count: int = Field(default=4, ge=1, le=6)
    orthogonal_only: bool = True           # diagonals are hard to build; the search adds only horizontal and vertical runs

    @model_validator(mode="after")
    def known_standards(self):
        if len(set(self.standards)) != len(self.standards):
            raise ValueError("standards must not contain duplicates")
        unknown = sorted(set(self.standards) - set(safety_criteria.SUPPORTED_STANDARDS))
        if unknown:
            raise ValueError("unsupported standards: " + ", ".join(unknown))
        return self


def dispatch_topology_run(run_id: str) -> None:
    from src.infrastructure.entrypoint.worker.tasks import optimize_topology

    optimize_topology.apply_async(args=[run_id], task_id=f"optimizer-topology:{run_id}")


def max_runs_per_project() -> int:
    """Topological runs a project may have queued or running at once (OPTIMIZER_MAX_RUNS_PER_PROJECT, default 1)."""
    try:
        return max(1, int(os.getenv("OPTIMIZER_MAX_RUNS_PER_PROJECT", "1")))
    except ValueError:
        return 1


SITE_KEYS = ("length_m", "width_m", "burial_depth_m", "areas", "structures")


@router.post("/topology", status_code=202)
def create_topology_run(project_id: str, payload: TopologyRunRequest, request: Request,
                        actor=Depends(require("designs:write"))):
    """Queue a topological search over the saved site of an artifact version; poll the run for its result."""
    now = int(time())
    request_data = payload.model_dump(mode="json")
    with request.app.state.services.store.transaction(write=True) as db:
        project = _owned_project(db, project_id, actor)
        repository = OptimizerRunRepository(db.connection)
        if repository.count_active_runs(project_id, topology_job.TOPOLOGY_ALGORITHM) >= max_runs_per_project():
            raise HTTPException(409, "This project already has an optimizer run in progress; wait for it or cancel it")
        artifact_row = db.designs.get_version(project_id, payload.artifact_id, payload.artifact_version)
        if not artifact_row:
            raise HTTPException(404, "Artifact version not found in this project")
        try:
            snapshot = validate_artifact(artifact_row["snapshot"])
        except ValueError as exc:
            raise HTTPException(422, f"Stored artifact is invalid: {exc}") from exc
        if snapshot.get("schema_version") != "1.0" or not snapshot.get("geometry"):
            raise HTTPException(422, "The topological optimizer supports version 1.0 artifacts with one grid geometry")
        geometry = snapshot["geometry"]
        if any(geometry.get(key) is None for key in ("length_m", "width_m")):
            raise HTTPException(422, "The artifact geometry must define the site length and width")
        # The soil is the artifact's own (1 to 8 layers), never a separate form value, so the search
        # optimizes over the same soil as the plan.
        try:
            request_data["soil"] = soil_record(artifact_potential.soil_model(snapshot["soil_layers"]))
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, f"The artifact soil cannot be used by the optimizer: {exc}") from exc
        selected = ConstraintProfileRepository(db.connection).selected(project_id)
        if any(row["status"] != "reviewed" for row in selected):
            raise HTTPException(409, "A selected profile is no longer reviewed; select a reviewed version")
        context = _selected_context(project, selected, ["rod_length_m"])
        facts = dict(payload.applicability_facts.values)
        facts["country"] = project.get("country")
        facts["installation_type"] = context.get("profile", {}).get("installation_type")
        context["applicability_facts"] = facts
        if context.get("status") != "ready":
            raise HTTPException(422, "OP-05 context is blocked: " + ", ".join(
                context.get("missing_mandatory_criteria") or ["unknown constraint"]))
        catalog_rows = MaterialCatalogRepository(db.connection).list(project_id, "approved")
        try:
            built = topology_job.build_rate_card(
                {key: value.model_dump() for key, value in payload.rates.items()}, currency=payload.cost_currency,
                trench_width_m=payload.trench_width_m, trench_width_source=payload.trench_width_source,
                catalog_rows=catalog_rows, now_epoch_s=now)
            missing = topology_job.check_rate_card_covers(built["rate_card"], [geometry])
            if missing:
                raise HTTPException(422, "The rate card leaves cost lines unpriced: " + ", ".join(missing))
            _, applied = topology_job.operator_constraints(context, orthogonal=payload.orthogonal_only, geometry=geometry)
            base_cost = evaluate_geometry_cost(geometry, built["rate_card"])
        except topology_job.RateCardError as exc:
            raise HTTPException(422, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        conductor = snapshot.get("conductor") or {}
        settings = ({"conductor_radius_m": equivalent_radius_m(float(conductor["cross_section_mm2"]))}
                    if conductor.get("cross_section_mm2") else None)
        run_id = str(uuid4())
        request_snapshot = {
            "algorithm": topology_job.TOPOLOGY_ALGORITHM,
            "strategy": topology_job.TOPOLOGY_STRATEGY,
            "request": request_data,
            "constraint_context": context,
            "site": geometry,
            "initial_geometry": geometry,
            "settings": settings,
            "rate_card": built["rate_card"],
            "rate_provenance": built["provenance"],
            "operator_constraints": applied,
            "parallel_workers": optimizer_topology_inputs.parallel_workers(),
            "base": {"artifact_version": payload.artifact_version, "cost": float(base_cost["total"]),
                     "cost_status": base_cost["status"], "cost_by_group": base_cost["by_group"],
                     "complexity": topology_job.complexity(geometry),
                     "electrical": "not evaluated by the optimizer; see the artifact's own potential calculation"},
            "artifact_snapshot_sha256": hashlib.sha256(json.dumps(
                snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest(),
        }
        run = repository.create_run({
            "id": run_id, "project_id": project_id, "artifact_id": payload.artifact_id,
            "artifact_version": payload.artifact_version, "status": "queued",
            "request_snapshot": request_snapshot, "result_summary": {"progress": {"verdicts": 0}}, "error": None,
            "created_by": actor.user_id, "created_at": now, "updated_at": now,
        })
    try:
        dispatch_topology_run(run_id)
    except Exception as exc:
        with request.app.state.services.store.transaction(write=True) as db:
            OptimizerRunRepository(db.connection).transition(project_id, run_id, ("queued",), {
                "status": "failed", "error": "The optimizer queue is unavailable", "updated_at": int(time())})
        raise HTTPException(503, "The optimizer queue is unavailable; try again later") from exc
    return {"run": run, "alternatives": []}


@router.post("/{run_id}/cancel")
def cancel_optimizer_run(project_id: str, run_id: str, request: Request, actor=Depends(require("designs:write"))):
    """Cancel a queued or running run. A running search stops after its current solver call."""
    with request.app.state.services.store.transaction(write=True) as db:
        _owned_project(db, project_id, actor)
        repo = OptimizerRunRepository(db.connection)
        run = repo.get_run(project_id, run_id)
        if not run:
            raise HTTPException(404, "Optimizer run not found")
        moved = repo.transition(project_id, run_id, ("queued", "running"), {
            "status": "cancelled", "error": None, "updated_at": int(time())})
        if moved is None:
            raise HTTPException(409, f"The run is already {run['status']}")
    return {"run": moved}


@router.get("/{run_id}/comparison")
def compare_optimizer_run(project_id: str, run_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        _owned_project(db, project_id, actor)
        repo = OptimizerRunRepository(db.connection)
        run = repo.get_run(project_id, run_id)
        if not run:
            raise HTTPException(404, "Optimizer run not found")
        alternatives = repo.list_alternatives(project_id, run_id)
    return topology_job.compare_alternatives(run, alternatives)


@router.post("/{run_id}/alternatives/{alternative_id}/apply", status_code=201)
def apply_optimizer_alternative(project_id: str, run_id: str, alternative_id: str, request: Request,
                                actor=Depends(require("designs:write"))):
    """Append a new artifact version with the alternative's geometry (BL-20); history is never rewritten."""
    from src.infrastructure.entrypoint.api.artifact_routes import announce_user_artifact_update

    with request.app.state.services.store.transaction(write=True) as db:
        _owned_project(db, project_id, actor)
        repo = OptimizerRunRepository(db.connection)
        run = repo.get_run(project_id, run_id)
        if not run or run["status"] != "completed":
            raise HTTPException(404, "Completed optimizer run not found")
        alternative = next((a for a in repo.list_alternatives(project_id, run_id) if a["id"] == alternative_id), None)
        if alternative is None:
            raise HTTPException(404, "Alternative not found in this run")
        source = db.designs.get_version(project_id, run["artifact_id"], run["artifact_version"])
        if not source:
            raise HTTPException(404, "The run's artifact version no longer exists")
        geometry = (alternative["evaluation_snapshot"].get("geometry")
                    or (alternative["candidate_snapshot"] or {}).get("geometry"))
        if not geometry:
            raise HTTPException(422, "This alternative carries no geometry to apply")
        new_snapshot = {**source["snapshot"], "geometry": geometry}
        try:
            validate_artifact(new_snapshot)
        except ValueError as exc:
            raise HTTPException(422, f"The alternative does not form a valid artifact: {exc}") from exc
        previous = db.designs.latest(project_id, run["artifact_id"])
        origin = {"kind": "user", "optimizer": {
            "run_id": run_id, "alternative_id": alternative_id, "candidate_sha256": alternative["candidate_sha256"],
            "algorithm": (run["request_snapshot"] or {}).get("algorithm", "discrete_local_search"),
            "based_on_version": run["artifact_version"], "certified": False}}
        row = db.designs.append_version(project_id, run["artifact_id"], source["name"], new_snapshot, actor.user_id, origin)
        cost = alternative["evaluation_snapshot"].get("cost")
        announce_user_artifact_update(
            db, project_id, row, previous,
            f"Se aplicó la alternativa {alternative.get('rank') or ''} del optimizador (costo {cost}); "
            "es un borrador sin certificar que requiere aprobación profesional")
        revalidation = _queue_revalidation(db, project_id, run, alternative, row, actor.user_id)
    if revalidation["status"] == "pending":
        # Dispatch only after the database transaction has committed, like a manual calculation request.
        try:
            calculate_artifact_potential.apply_async(args=[revalidation["calculation_id"]], task_id=revalidation["calculation_id"])
        except Exception:
            potential_calculations.mark_dispatch_failed(request.app.state.services.store, revalidation["calculation_id"])
            revalidation = {**revalidation, "status": "failed", "detail": "No se pudo encolar el cálculo de revalidación"}
    return {**row, "revalidation": revalidation}


def revalidation_parameters(run: dict[str, Any], alternative: dict[str, Any]) -> dict[str, Any]:
    """OP-07: the applied alternative is recalculated with the full solver on the validated fine mesh (the same
    defaults a manual calculation uses) and the standards the search was asked to satisfy. The exposure comes
    from the artifact itself, as in any calculation of that version, so the study shows the artifact's verdict."""
    request_snapshot = (run.get("request_snapshot") or {}).get("request") or {}
    standards = [s for s in request_snapshot.get("standards") or [] if s in safety_criteria.SUPPORTED_STANDARDS]
    evaluation = alternative.get("evaluation_snapshot") or {}
    justification = (f"Revalidación OP-07 de la alternativa {alternative['id']} de la corrida {run['id']} con el solver "
                     f"completo y malla fina; la búsqueda la validó en {evaluation.get('validated_at_level') or 'malla gruesa'}.")
    payload = PotentialCalculationRequest(justification=justification[:500], estimate_uncertainty=True,
                                          **({"safety_standards": standards} if standards else {}))
    return payload.model_dump()


def _queue_revalidation(db, project_id: str, run: dict[str, Any], alternative: dict[str, Any], version_row: dict[str, Any],
                        actor_id: str) -> dict[str, Any]:
    """Insert the pending OP-07 calculation for the new version; a blocked artifact never undoes the apply."""
    try:
        calculation = potential_calculations.create_calculation(
            db, project_id, version_row["artifact_id"], version_row["version"], revalidation_parameters(run, alternative), actor_id)
    except potential_calculations.CalculationBlocked as exc:
        return {"status": "blocked", "calculation_id": None, "detail": exc.detail}
    return {"status": "pending", "calculation_id": calculation["id"], "detail": None}
