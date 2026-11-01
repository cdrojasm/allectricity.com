"""Synchronous project-scoped endpoint for discrete optimizer runs (OP-06/OP-19)."""

from __future__ import annotations

import hashlib
import json
from time import time
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.application.use_cases.optimizer_run import run_discrete_optimizer
from src.domain.spat.artifact_contract import validate_artifact
from src.infrastructure.calculations import safety_criteria
from src.infrastructure.calculations.conductor_thermal import equivalent_radius_m
from src.infrastructure.calculations.potential_engine_client import (
    HomogeneousSoil,
    LayerStackSoil,
    PotentialEngineClient,
    TwoLayerSoil,
)
from src.infrastructure.entrypoint.api.constraint_profile_routes import (
    _attach_site_domain,
    _owned_project,
    _selected_context,
)
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
