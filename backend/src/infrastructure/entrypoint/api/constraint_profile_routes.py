"""Versioned rule profiles and the reviewed versions pinned to projects.

Who does what (scope of the profile, see constraint_profile_repository):
- default:  shipped IEEE 80 / RETIE profiles; everyone sees and pins them; only a super_admin may retire a version.
- catalog:  a super_admin creates, versions, reviews and retires them; everyone sees and pins the reviewed ones.
- personal: any designer creates one for their own projects; only its owner sees, versions, reviews, retires
            and pins it (a super_admin may see and manage every profile).
"""

from __future__ import annotations

from time import time
from typing import Any, Literal
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import IntegrityError

from src.domain.spat.default_normative_profiles import STANDARD_PROFILES
from src.domain.spat.optimizer_constraints import compile_site_translation_bounds, resolve_optimizer_constraints
from src.domain.spat.discrete_domains import resolve_discrete_domains
from src.infrastructure.persistence.constraint_profile_repository import ConstraintProfileRepository
from src.infrastructure.persistence.material_catalog_repository import MaterialCatalogRepository
from src.infrastructure.services.optimizer_material_options import approved_material_domains
from src.infrastructure.security.middleware import require


router = APIRouter(tags=["constraint-profiles"])


class ConstraintRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=160)
    category: Literal["mandatory", "guidance", "constructability", "commercial"]
    target: str | None = Field(default=None, min_length=1, max_length=240)
    criterion: str | None = Field(default=None, min_length=1, max_length=160)
    applicability: Literal["applicable", "not_applicable", "unknown"]
    applicability_conditions: list[str] = Field(min_length=1, max_length=40)
    verification_method: str = Field(min_length=1, max_length=500)
    expression: str | None = Field(default=None, max_length=2000)
    min: float | None = None
    max: float | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=40)
    source: dict[str, Any] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_range(self):
        has_min, has_max = self.min is not None, self.max is not None
        if has_min != has_max:
            raise ValueError("min and max must be provided together")
        if has_min and (self.unit is None or self.target is None):
            raise ValueError("bounded rules require target and unit")
        if has_min and self.min > self.max:
            raise ValueError("min must not exceed max")
        if any(not condition.strip() for condition in self.applicability_conditions):
            raise ValueError("applicability_conditions must contain nonempty explanations")
        if self.category in {"mandatory", "guidance"}:
            if any(not isinstance(self.source.get(key), str) or not self.source[key].strip()
                   for key in ("document", "edition", "clause")):
                raise ValueError("normative source must include document, edition, and clause")
        elif not any(isinstance(self.source.get(key), str) and self.source[key].strip()
                     for key in ("reference", "item_id", "document")):
            raise ValueError("constructability and commercial sources need a reference, item_id, or document")
        return self


class ConstraintProfileDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=180)
    jurisdiction: str = Field(min_length=1, max_length=120)
    installation_type: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    required_mandatory_criteria: list[str]
    rules: list[ConstraintRuleInput] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique_criteria(self):
        if len(set(self.required_mandatory_criteria)) != len(self.required_mandatory_criteria):
            raise ValueError("required_mandatory_criteria must not contain duplicates")
        return self


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    profile_id: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]+$")
    definition: ConstraintProfileDefinition
    # Only a super_admin may publish to the shared catalog; for anyone else the profile is personal.
    scope: Literal["catalog", "personal"] | None = None


class ProfileVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: ConstraintProfileDefinition


class ProjectProfileSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles: list[dict[str, Any]] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_items(self):
        allowed = {"profile_id", "version"}
        seen = set()
        for item in self.profiles:
            if set(item) != allowed or not isinstance(item.get("profile_id"), str) \
                    or isinstance(item.get("version"), bool) or not isinstance(item.get("version"), int) \
                    or item["version"] < 1:
                raise ValueError("each selection requires profile_id and a positive integer version")
            if item["profile_id"] in seen:
                raise ValueError("select at most one version of each profile")
            seen.add(item["profile_id"])
        return self


class ConstraintContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_variables: list[str] = Field(default_factory=list, max_length=200)
    site_geometry: dict[str, Any] | None = None
    applicability_facts: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_variables(self):
        if len(set(self.requested_variables)) != len(self.requested_variables):
            raise ValueError("requested_variables must not contain duplicates")
        return self


def _profile_definition(profile_id, version, definition):
    return {
        "profile_id": profile_id,
        "version": str(version),
        "jurisdiction": definition["jurisdiction"],
        "installation_type": definition["installation_type"],
        "required_mandatory_criteria": definition["required_mandatory_criteria"],
        "rules": definition["rules"],
    }


def _validate_definition(profile_id, version, definition):
    try:
        return resolve_optimizer_constraints(
            _profile_definition(profile_id, version, definition), [],
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _visible(row, actor) -> bool:
    """Whether the actor may see this profile version at all."""
    if actor.privileged:
        return True
    if row.get("scope") == "personal":
        return row.get("owner_id") == actor.user_id
    return row["status"] == "reviewed"


def _manageable(repo, profile_id, actor) -> dict:
    """The profile, if the actor may add versions to it, review or retire it; 404/403 otherwise."""
    profile = repo.profile(profile_id)
    if profile is None or (profile["scope"] == "personal" and not actor.privileged
                           and profile["owner_id"] != actor.user_id):
        raise HTTPException(404, "Constraint profile not found")
    if profile["scope"] == "personal" and profile["owner_id"] == actor.user_id:
        return profile
    if not actor.privileged:
        raise HTTPException(403, "Only a privileged curator can change shared profiles")
    return profile


def _owned_project(db, project_id, actor):
    project = db.one("projects", id=project_id)
    if not project or (not actor.privileged and project["owner_id"] != actor.user_id):
        raise HTTPException(404, "Project not found")
    return project


def _normalize_location(value):
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in normalized if not unicodedata.combining(char)).strip().casefold()


def _selected_context(project, selected, requested_variables):
    if not selected:
        return {
            "schema_version": "spat.optimizer-constraints/1.0",
            "profile": {"profile_id": f"project:{project['id']}", "version": "none",
                        "jurisdiction": project.get("country") or "unconfirmed",
                        "installation_type": "unconfirmed"},
            "status": "blocked",
            "missing_mandatory_criteria": ["normative_profile_not_selected"],
            "variable_bounds": {},
            "optimizable_variables": [],
            "frozen_variables": {path: "normative_profile_not_selected" for path in requested_variables},
            "bound_provenance": {},
            "selected_profiles": [],
        }

    definitions = [item["definition"] for item in selected]
    installation_types = {definition["installation_type"].casefold() for definition in definitions}
    if len(installation_types) != 1:
        raise HTTPException(409, "Selected profiles apply to different installation types")

    country = project.get("country")
    jurisdictions = {definition["jurisdiction"] for definition in definitions
                     if _normalize_location(definition["jurisdiction"]) not in {"global", "international"}}
    jurisdiction_mismatch = bool(jurisdictions) and (
        not country or any(_normalize_location(item) != _normalize_location(country) for item in jurisdictions)
    )

    combined_rules = []
    required = []
    selected_refs = []
    for item in selected:
        profile_id, version = item["profile_id"], item["profile_version"]
        definition = item["definition"]
        required.extend(definition["required_mandatory_criteria"])
        selected_refs.append({"profile_id": profile_id, "version": version,
                              "jurisdiction": definition["jurisdiction"],
                              "installation_type": definition["installation_type"]})
        for rule in definition["rules"]:
            combined_rules.append({**rule, "id": f"{profile_id}@{version}:{rule['id']}"})

    composite = {
        "profile_id": f"project:{project['id']}",
        "version": "+".join(f"{item['profile_id']}@{item['profile_version']}" for item in selected),
        "jurisdiction": country or "unconfirmed",
        "installation_type": definitions[0]["installation_type"],
        "required_mandatory_criteria": list(dict.fromkeys(required)),
        "rules": combined_rules,
    }
    result = resolve_optimizer_constraints(composite, requested_variables)
    result["selected_profiles"] = selected_refs
    if not composite["required_mandatory_criteria"]:
        result["status"] = "blocked"
        result["missing_mandatory_criteria"] = ["mandatory_safety_profile_not_selected"]
        result["optimizable_variables"] = []
        for variable in requested_variables:
            result["frozen_variables"][variable] = "mandatory_safety_profile_not_selected"
    if jurisdiction_mismatch:
        result["status"] = "blocked"
        result["missing_mandatory_criteria"] = sorted(set(result["missing_mandatory_criteria"])
                                                       | {"jurisdiction_profile_mismatch"})
        for variable in requested_variables:
            result["variable_bounds"].pop(variable, None)
            result["bound_provenance"].pop(variable, None)
            result["frozen_variables"][variable] = "jurisdiction_profile_mismatch"
        result["optimizable_variables"] = []
    return result


def _attach_site_domain(context: dict[str, Any], site_geometry: dict[str, Any] | None,
                        requested_variables: list[str]) -> dict[str, Any]:
    if site_geometry is None:
        return context
    domain = compile_site_translation_bounds(site_geometry, requested_variables)
    bounds = context.setdefault("variable_bounds", {})
    provenance = context.setdefault("bound_provenance", {})
    frozen = context.setdefault("frozen_variables", {})
    for variable, interval in domain["bounds"].items():
        if context.get("status") != "ready":
            frozen[variable] = "mandatory_criteria_missing"
            continue
        current = bounds.get(variable)
        if current:
            interval = {"min": max(current["min"], interval["min"]),
                        "max": min(current["max"], interval["max"])}
            if interval["min"] > interval["max"]:
                bounds.pop(variable, None)
                provenance.pop(variable, None)
                frozen[variable] = "conflicting_site_and_profile_bounds"
                continue
            provenance[variable] = [*provenance.get(variable, []), *domain["provenance"][variable]]
        else:
            provenance[variable] = domain["provenance"][variable]
        bounds[variable] = interval
        frozen.pop(variable, None)
    for variable, reason in domain["frozen_variables"].items():
        if variable not in bounds:
            frozen[variable] = reason
    context["optimizable_variables"] = sorted(bounds) if context.get("status") == "ready" else []
    context["site_geometry_sha256"] = next((entries[0]["site_geometry_sha256"]
                                             for entries in domain["provenance"].values()), None)
    context["geometry_candidate_filter"] = "geometry_conflicts (intervenible polygons, exclusions, obstacles, contacts, topology)"
    return context


@router.get("/api/v1/constraint-profiles")
def list_constraint_profiles(
    request: Request,
    include_drafts: bool = False,
    actor=Depends(require("designs:read")),
):
    if include_drafts and not actor.privileged:
        raise HTTPException(403, "Only a privileged curator can list draft profiles")
    with request.app.state.services.store.transaction() as db:
        rows = ConstraintProfileRepository(db.connection).all_versions()
        if include_drafts:
            return {"profiles": rows, "standard_profiles": STANDARD_PROFILES}
        # Reviewed shared profiles plus every version of the actor's own personal profiles.
        rows = [row for row in rows if (row["scope"] == "personal" and row["owner_id"] == actor.user_id)
                or (row["scope"] != "personal" and row["status"] == "reviewed")]
        return {"profiles": rows, "standard_profiles": STANDARD_PROFILES}


@router.post("/api/v1/constraint-profiles", status_code=201)
def create_constraint_profile(
    payload: ProfileCreate,
    request: Request,
    actor=Depends(require("designs:write")),
):
    if payload.scope == "catalog" and not actor.privileged:
        raise HTTPException(403, "Only a privileged curator can publish to the shared catalog")
    scope = payload.scope or ("catalog" if actor.privileged else "personal")
    definition = payload.definition.model_dump(exclude_none=True)
    _validate_definition(payload.profile_id, 1, definition)
    now = int(time())
    try:
        with request.app.state.services.store.transaction(write=True) as db:
            repo = ConstraintProfileRepository(db.connection)
            row = repo.create_profile(payload.profile_id, actor.user_id, definition, now, scope=scope)
            return row
    except IntegrityError as exc:
        raise HTTPException(409, "Constraint profile id already exists") from exc


@router.get("/api/v1/constraint-profiles/{profile_id}/versions/{version}")
def get_constraint_profile_version(
    profile_id: str,
    version: int,
    request: Request,
    actor=Depends(require("designs:read")),
):
    with request.app.state.services.store.transaction() as db:
        row = ConstraintProfileRepository(db.connection).get_version(profile_id, version)
        if not row or not _visible(row, actor):
            raise HTTPException(404, "Constraint profile version not found")
        return row


@router.post("/api/v1/constraint-profiles/{profile_id}/versions", status_code=201)
def create_constraint_profile_version(
    profile_id: str,
    payload: ProfileVersionCreate,
    request: Request,
    actor=Depends(require("designs:write")),
):
    definition = payload.definition.model_dump(exclude_none=True)
    with request.app.state.services.store.transaction(write=True) as db:
        repo = ConstraintProfileRepository(db.connection)
        if _manageable(repo, profile_id, actor)["scope"] == "default":
            raise HTTPException(403, "Shipped profiles change only with the app; save your changes as a new profile")
        version = repo.next_version(profile_id)
        _validate_definition(profile_id, version, definition)
        return repo.create_version(profile_id, version, definition, actor.user_id, int(time()))


@router.post("/api/v1/constraint-profiles/{profile_id}/versions/{version}/review")
def review_constraint_profile_version(
    profile_id: str,
    version: int,
    request: Request,
    actor=Depends(require("designs:write")),
):
    with request.app.state.services.store.transaction(write=True) as db:
        repo = ConstraintProfileRepository(db.connection)
        _manageable(repo, profile_id, actor)
        row = repo.get_version(profile_id, version)
        if not row:
            raise HTTPException(404, "Constraint profile version not found")
        if row["status"] != "draft":
            raise HTTPException(409, "Only draft profile versions can be reviewed")
        definition = row["definition"]
        compiled = _validate_definition(profile_id, version, definition)
        if compiled["status"] != "ready":
            raise HTTPException(422, {
                "message": "The profile is missing applicable rules for mandatory criteria",
                "missing_mandatory_criteria": compiled["missing_mandatory_criteria"],
            })
        return repo.review(profile_id, version, actor.user_id, int(time()))


@router.post("/api/v1/constraint-profiles/{profile_id}/versions/{version}/retire")
def retire_constraint_profile_version(
    profile_id: str,
    version: int,
    request: Request,
    actor=Depends(require("designs:write")),
):
    with request.app.state.services.store.transaction(write=True) as db:
        repo = ConstraintProfileRepository(db.connection)
        _manageable(repo, profile_id, actor)
        row = repo.get_version(profile_id, version)
        if not row:
            raise HTTPException(404, "Constraint profile version not found")
        if row["status"] != "reviewed":
            raise HTTPException(409, "Only reviewed profile versions can be retired")
        return repo.retire(profile_id, version, actor.user_id, int(time()))


@router.get("/api/v1/projects/{project_id}/constraint-profiles")
def get_project_constraint_profiles(
    project_id: str,
    request: Request,
    actor=Depends(require("designs:read")),
):
    with request.app.state.services.store.transaction() as db:
        _owned_project(db, project_id, actor)
        return {"profiles": ConstraintProfileRepository(db.connection).selected(project_id)}


@router.put("/api/v1/projects/{project_id}/constraint-profiles")
def set_project_constraint_profiles(
    project_id: str,
    payload: ProjectProfileSelection,
    request: Request,
    actor=Depends(require("designs:write")),
):
    with request.app.state.services.store.transaction(write=True) as db:
        _owned_project(db, project_id, actor)
        repo = ConstraintProfileRepository(db.connection)
        project = db.one("projects", id=project_id)
        for selection in payload.profiles:
            row = repo.get_version(selection["profile_id"], selection["version"])
            if not row or row["status"] != "reviewed":
                raise HTTPException(422, "Projects may only pin reviewed profile versions")
            # A personal profile belongs to its owner: it may only be pinned to that owner's projects.
            if row["scope"] == "personal" and row["owner_id"] not in {actor.user_id, project["owner_id"]}:
                raise HTTPException(422, "A personal profile can only be pinned to its owner's projects")
        rows = repo.select_for_project(project_id, payload.profiles, actor.user_id, int(time()))
        return {"profiles": rows}


@router.post("/api/v1/projects/{project_id}/constraint-context")
def resolve_project_constraint_context(
    project_id: str,
    payload: ConstraintContextRequest,
    request: Request,
    actor=Depends(require("designs:read")),
):
    with request.app.state.services.store.transaction() as db:
        project = _owned_project(db, project_id, actor)
        repo = ConstraintProfileRepository(db.connection)
        selected = repo.selected(project_id)
        if any(row["status"] != "reviewed" for row in selected):
            raise HTTPException(409, "A selected profile is no longer reviewed; select a reviewed version")
        context = _selected_context(project, selected, payload.requested_variables)
        try:
            context = _attach_site_domain(context, payload.site_geometry, payload.requested_variables)
            approved_rows = MaterialCatalogRepository(db.connection).list(project_id, "approved")
            domains = approved_material_domains(approved_rows, now_epoch_s=int(time()))
            facts = dict(payload.applicability_facts)
            facts["country"] = project.get("country")
            facts["installation_type"] = context.get("profile", {}).get("installation_type")
            resolved_domains = resolve_discrete_domains(domains, facts)
            context["applicability_facts"] = facts
            if context.get("status") == "ready":
                discrete_variables = sorted({domain["target"] for domain in resolved_domains["domains"]
                                             if domain["status"] == "ready" and domain["candidate_values"]})
            else:
                discrete_variables = []
            context["discrete_domains"] = resolved_domains
            context["discrete_optimizable_variables"] = discrete_variables
            context["material_domain_snapshot"] = [
                {"domain_id": domain["domain_id"], "target": domain["target"],
                 "catalog_item_versions": sorted({option["provenance"].get("catalog_item_id", "") + "@v"
                                                   + str(option["provenance"].get("catalog_version", ""))
                                                   for option in domain["options"]})}
                for domain in domains
            ]
            return context
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
