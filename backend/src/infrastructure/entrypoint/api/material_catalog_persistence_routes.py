"""Project scoped material catalog CRUD and quote version history."""

from decimal import Decimal
from math import isfinite
import re
from time import time
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.infrastructure.persistence.material_catalog_repository import (
    EDITABLE_FIELDS,
    MaterialCatalogRepository,
)
from src.infrastructure.security.middleware import require


router = APIRouter(
    prefix="/api/v1/projects/{project_id}/material-catalog",
    tags=["material-catalog"],
)
personal_router = APIRouter(prefix="/api/v1/material-catalog/personal", tags=["material-catalog"])


_STRUCTURED_TARGET_UNITS = {"rod_length_m": "m"}


class StructuredOptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    option_id: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=100)
    value: float
    unit: str = Field(min_length=1, max_length=20)
    applicability_filters: dict[str, str | int | float | bool | list[str | int | float | bool]] = Field(default_factory=dict)
    provenance: dict = Field(min_length=1)

    @model_validator(mode="after")
    def validate_engineering_mapping(self):
        expected_unit = _STRUCTURED_TARGET_UNITS.get(self.target)
        if expected_unit is None and re.fullmatch(r"rod_lengths_m\[\d+\]", self.target):
            expected_unit = "m"
        if expected_unit is None:
            raise ValueError("target must be a supported numeric OP-02 parameter")
        if self.unit != expected_unit:
            raise ValueError(f"{self.target} requires unit {expected_unit}")
        if not isfinite(self.value) or self.value <= 0:
            raise ValueError("engineering option values must be positive finite numbers")
        source_type = self.provenance.get("source_type")
        reference = next((self.provenance.get(key) for key in ("reference", "document", "source_url")
                          if isinstance(self.provenance.get(key), str) and self.provenance[key].strip()), None)
        if not isinstance(source_type, str) or not source_type.strip() or reference is None:
            raise ValueError("option provenance requires source_type and a nonempty reference, document, or source_url")
        source_url = self.provenance.get("source_url")
        if source_url is not None:
            parsed = urlparse(source_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("option provenance source_url must be an http(s) URL")
        return self


class StructuredOptionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    domain_id: str = Field(min_length=1, max_length=160)
    options: list[StructuredOptionInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def options_share_domain_semantics(self):
        identities = [option.option_id for option in self.options]
        if len(set(identities)) != len(identities):
            raise ValueError("structured option IDs must be unique within the domain")
        meanings = {(option.target, option.unit) for option in self.options}
        if len(meanings) != 1:
            raise ValueError("all structured options in a domain must share target and unit")
        return self


class ServiceDetailsInput(BaseModel):
    """Explicit commercial and delivery terms for a service catalog entry."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    pricing_type: Literal["fixed", "measured"]
    scope: str = Field(min_length=1, max_length=3000)
    acceptance_criteria: str | None = Field(default=None, max_length=3000)
    work_duration: str | None = Field(default=None, max_length=240)
    wait_duration: str | None = Field(default=None, max_length=240)


class ContactDataInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=60)
    whatsapp_url: str | None = Field(default=None, max_length=2000)
    contact_url: str | None = Field(default=None, max_length=2000)
    image_url: str | None = Field(default=None, max_length=2000)


class AvailabilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    lead_time: str | None = Field(default=None, max_length=240)
    lead_time_type: Literal["dispatch", "work"] = "dispatch"
    source_url: str | None = Field(default=None, max_length=2000)
    checked_at: int | None = Field(default=None, ge=0)


def _validate_service_details(category, service_details):
    if category == "Servicio" and service_details is None:
        raise ValueError("service_details is required for service catalog items")
    if category != "Servicio" and service_details is not None:
        raise ValueError("service_details is only valid for service catalog items")


def _validate_service_unit(category, quantity_unit, service_details):
    _validate_service_details(category, service_details)
    if service_details and service_details.pricing_type == "fixed" and quantity_unit != "servicio":
        raise ValueError("fixed-price services must use quantity_unit 'servicio'")
    if service_details and service_details.pricing_type == "measured" and quantity_unit == "servicio":
        raise ValueError("measured services must declare a measurable quantity_unit")


class MaterialItemInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=240)
    category: str = Field(min_length=1, max_length=60)
    material: str | None = Field(default=None, max_length=160)
    specification: str = Field(min_length=1, max_length=5000)
    structured_options: StructuredOptionsInput | None = None
    service_details: ServiceDetailsInput | None = None
    contact_data: ContactDataInput | None = None
    availability: AvailabilityInput | None = None
    field_provenance: dict = Field(default_factory=dict)
    quantity: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    quantity_unit: str | None = Field(default=None, max_length=40)
    quantity_basis: str | None = Field(default=None, max_length=2000)
    price_per_unit: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    price_currency: str | None = Field(default=None, min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    supplier: str | None = Field(default=None, max_length=240)
    source_name: str | None = Field(default=None, max_length=240)
    source_url: str | None = Field(default=None, max_length=2000)
    country: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    quoted_at: int | None = Field(default=None, ge=0)
    expires_at: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("source_url")
    @classmethod
    def valid_source_url(cls, value):
        if value is None or value == "":
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an http(s) URL")
        return value

    @model_validator(mode="after")
    def validate_quote(self):
        _validate_service_unit(self.category, self.quantity_unit, self.service_details)
        if self.price_per_unit is not None and not self.price_currency:
            raise ValueError("price_currency is required with price_per_unit")
        if self.expires_at is not None and self.quoted_at is not None and self.expires_at < self.quoted_at:
            raise ValueError("expires_at must be on or after quoted_at")
        return self


class MaterialItemPatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=240)
    category: str | None = Field(default=None, min_length=1, max_length=60)
    material: str | None = Field(default=None, max_length=160)
    specification: str | None = Field(default=None, min_length=1, max_length=5000)
    structured_options: StructuredOptionsInput | None = None
    service_details: ServiceDetailsInput | None = None
    contact_data: ContactDataInput | None = None
    availability: AvailabilityInput | None = None
    field_provenance: dict | None = None
    quantity: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    quantity_unit: str | None = Field(default=None, max_length=40)
    quantity_basis: str | None = Field(default=None, max_length=2000)
    price_per_unit: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    price_currency: str | None = Field(default=None, min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    supplier: str | None = Field(default=None, max_length=240)
    source_name: str | None = Field(default=None, max_length=240)
    source_url: str | None = Field(default=None, max_length=2000)
    country: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    quoted_at: int | None = Field(default=None, ge=0)
    expires_at: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("source_url")
    @classmethod
    def valid_source_url(cls, value):
        if value is None or value == "":
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an http(s) URL")
        return value

    @model_validator(mode="after")
    def validate_non_null_required_fields(self):
        for field in ("name", "category", "specification"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

class ApprovalInput(BaseModel):
    approved: bool


def _owned_project(db, project_id, actor):
    project = db.one("projects", id=project_id)
    if not project or (not actor.privileged and project["owner_id"] != actor.user_id):
        raise HTTPException(404, "Project not found")
    return project


def _repository(db):
    return MaterialCatalogRepository(db.connection)


def _snapshot(repo, row, action, actor_id, now):
    repo.add_version({
        "id": str(uuid4()),
        "item_id": row["id"],
        "project_id": row["project_id"],
        "version": row["version"],
        "action": action,
        "snapshot": row,
        "created_by": actor_id,
        "created_at": now,
    })


def _with_quote_state(row):
    result = dict(row)
    result["quote_expired"] = bool(result.get("expires_at") and result["expires_at"] <= int(time()))
    return result


def _totals(rows):
    totals = {}
    for row in rows:
        if row["status"] != "approved" or row.get("estimated_cost") is None:
            continue
        currency = row["price_currency"]
        totals[currency] = totals.get(currency, Decimal("0")) + Decimal(row["estimated_cost"])
    result = [{"currency": currency, "amount": format(amount, "f")} for currency, amount in sorted(totals.items())]
    return result[0] if len(result) == 1 else None


@personal_router.get("")
def list_personal_catalog(request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        rows = [_with_quote_state(row) for row in _repository(db).list_personal(actor.user_id)]
        return {"items": rows, "estimated_total": _totals(rows)}


@personal_router.post("", status_code=201)
def create_personal_catalog_item(data: MaterialItemInput, request: Request, actor=Depends(require("designs:write"))):
    now = int(time())
    repo_cls = MaterialCatalogRepository
    with request.app.state.services.store.transaction(write=True) as db:
        repo = repo_cls(db.connection)
        row = repo.insert({**data.model_dump(), "id": str(uuid4()), "project_id": None,
            "created_by": actor.user_id, "updated_by": actor.user_id, "status": "candidate",
            "version": 1, "created_at": now, "updated_at": now})
        _snapshot(repo, row, "created", actor.user_id, now)
        return _with_quote_state(row)


@personal_router.patch("/{item_id}")
def update_personal_catalog_item(item_id: str, data: MaterialItemPatch, request: Request,
                                actor=Depends(require("designs:write"))):
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "At least one field must be provided")
    now = int(time())
    with request.app.state.services.store.transaction(write=True) as db:
        repo = _repository(db)
        current = repo.get_personal(actor.user_id, item_id)
        if not current:
            raise HTTPException(404, "Personal catalog item not found")
        if current["status"] == "archived":
            raise HTTPException(409, "Archived items cannot be edited")
        merged = {**current, **changes}
        details = merged.get("service_details")
        if details and isinstance(details, dict):
            details = ServiceDetailsInput.model_validate(details)
        _validate_service_unit(merged.get("category"), merged.get("quantity_unit"), details)
        row = repo.update_personal(actor.user_id, item_id, {**changes, "updated_by": actor.user_id,
            "version": current["version"] + 1, "updated_at": now})
        _snapshot(repo, row, "updated", actor.user_id, now)
        return _with_quote_state(row)


@personal_router.post("/{item_id}/approval")
def set_personal_catalog_approval(item_id: str, data: ApprovalInput, request: Request,
                                  actor=Depends(require("designs:write"))):
    now = int(time())
    with request.app.state.services.store.transaction(write=True) as db:
        repo = _repository(db)
        current = repo.get_personal(actor.user_id, item_id)
        if not current:
            raise HTTPException(404, "Personal catalog item not found")
        if current["status"] == "archived":
            raise HTTPException(409, "Archived items cannot be approved")
        if data.approved:
            if current.get("price_per_unit") is None or not current.get("supplier"):
                raise HTTPException(409, "Approval requires a price and supplier")
            if not current.get("source_url") and not current.get("notes"):
                raise HTTPException(409, "Approval requires a traceable source URL or note")
            if current.get("expires_at") and current["expires_at"] <= now:
                raise HTTPException(409, "Expired quotes cannot be approved")
        row = repo.update_personal(actor.user_id, item_id, {"status": "approved" if data.approved else "candidate",
            "updated_by": actor.user_id, "version": current["version"] + 1, "updated_at": now})
        _snapshot(repo, row, "approved" if data.approved else "unapproved", actor.user_id, now)
        return _with_quote_state(row)


@personal_router.delete("/{item_id}", status_code=204)
def archive_personal_catalog_item(item_id: str, request: Request, actor=Depends(require("designs:write"))):
    now = int(time())
    with request.app.state.services.store.transaction(write=True) as db:
        repo = _repository(db)
        current = repo.get_personal(actor.user_id, item_id)
        if not current:
            raise HTTPException(404, "Personal catalog item not found")
        if current["status"] != "archived":
            row = repo.update_personal(actor.user_id, item_id, {"status": "archived", "updated_by": actor.user_id,
                "version": current["version"] + 1, "updated_at": now})
            _snapshot(repo, row, "archived", actor.user_id, now)
    return None


@personal_router.get("/{item_id}/versions")
def personal_catalog_item_versions(item_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        if not _repository(db).get_personal(actor.user_id, item_id):
            raise HTTPException(404, "Personal catalog item not found")
        return {"versions": _repository(db).personal_versions(actor.user_id, item_id)}


@router.get("")
def list_material_catalog(
    project_id: str,
    request: Request,
    status: str | None = None,
    actor=Depends(require("designs:read")),
):
    if status not in {None, "candidate", "approved", "archived"}:
        raise HTTPException(422, "status must be candidate, approved, or archived")
    with request.app.state.services.store.transaction() as db:
        _owned_project(db, project_id, actor)
        repo = _repository(db)
        if status:
            rows = repo.list(project_id, status)
        else:
            rows = repo.list(project_id, "candidate") + repo.list(project_id, "approved")
        rows = [_with_quote_state(row) for row in rows]
        total = _totals(rows)
        grouped_totals = {}
        for row in rows:
            if row["status"] == "approved" and row.get("estimated_cost") is not None:
                currency = row["price_currency"]
                grouped_totals[currency] = grouped_totals.get(currency, Decimal("0")) + Decimal(row["estimated_cost"])
        totals = [{"currency": currency, "amount": format(amount, "f")} for currency, amount in sorted(grouped_totals.items())]
        return {"items": rows, "estimated_total": total, "estimated_totals": totals}


@router.get("/history")
def project_material_catalog_history(
    project_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    actor=Depends(require("designs:read")),
):
    """Return recent immutable snapshots across all catalog items in a project."""
    with request.app.state.services.store.transaction() as db:
        _owned_project(db, project_id, actor)
        return {"versions": _repository(db).recent_versions(project_id, limit)}


@router.post("", status_code=201)
def create_material_item(
    project_id: str,
    data: MaterialItemInput,
    request: Request,
    actor=Depends(require("designs:write")),
):
    now = int(time())
    with request.app.state.services.store.transaction(write=True) as db:
        _owned_project(db, project_id, actor)
        repo = _repository(db)
        values = data.model_dump()
        row = repo.insert({
            **values,
            "id": str(uuid4()),
            "project_id": project_id,
            "created_by": actor.user_id,
            "updated_by": actor.user_id,
            "status": "candidate",
            "version": 1,
            "created_at": now,
            "updated_at": now,
        })
        _snapshot(repo, row, "created", actor.user_id, now)
        return _with_quote_state(row)


@router.get("/{item_id}")
def get_material_item(project_id: str, item_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        _owned_project(db, project_id, actor)
        row = _repository(db).get(project_id, item_id)
        if not row:
            raise HTTPException(404, "Material catalog item not found")
        return _with_quote_state(row)


@router.patch("/{item_id}")
def update_material_item(
    project_id: str,
    item_id: str,
    data: MaterialItemPatch,
    request: Request,
    actor=Depends(require("designs:write")),
):
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "At least one field must be provided")
    now = int(time())
    with request.app.state.services.store.transaction(write=True) as db:
        _owned_project(db, project_id, actor)
        repo = _repository(db)
        current = repo.get(project_id, item_id)
        if not current:
            raise HTTPException(404, "Material catalog item not found")
        if current["status"] == "archived":
            raise HTTPException(409, "Archived items cannot be edited")
        merged = {**current, **changes}
        try:
            service_details = merged.get("service_details")
            if service_details and isinstance(service_details, dict):
                service_details = ServiceDetailsInput.model_validate(service_details)
            _validate_service_unit(merged.get("category"), merged.get("quantity_unit"), service_details)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if merged.get("price_per_unit") is not None and not merged.get("price_currency"):
            raise HTTPException(422, "price_currency is required with price_per_unit")
        if merged.get("expires_at") is not None and merged.get("quoted_at") is not None and merged["expires_at"] < merged["quoted_at"]:
            raise HTTPException(422, "expires_at must be on or after quoted_at")
        options_changed = ("structured_options" in changes
                           and changes["structured_options"] != current.get("structured_options"))
        row = repo.update(project_id, item_id, {
            **{key: value for key, value in changes.items() if key in EDITABLE_FIELDS},
            **({"status": "candidate"} if options_changed and current["status"] == "approved" else {}),
            "updated_by": actor.user_id,
            "version": current["version"] + 1,
            "updated_at": now,
        })
        _snapshot(repo, row, "updated", actor.user_id, now)
        return _with_quote_state(row)


@router.post("/{item_id}/approval")
def set_material_approval(
    project_id: str,
    item_id: str,
    data: ApprovalInput,
    request: Request,
    actor=Depends(require("designs:write")),
):
    now = int(time())
    with request.app.state.services.store.transaction(write=True) as db:
        _owned_project(db, project_id, actor)
        repo = _repository(db)
        current = repo.get(project_id, item_id)
        if not current:
            raise HTTPException(404, "Material catalog item not found")
        if current["status"] == "archived":
            raise HTTPException(409, "Archived items cannot be approved")
        if data.approved:
            if current.get("price_per_unit") is None or not current.get("supplier"):
                raise HTTPException(409, "Approval requires a price and supplier")
            if current.get("structured_options") and not current.get("quantity_unit"):
                raise HTTPException(409, "An option-bearing quote requires a price unit")
            if not current.get("source_url") and not current.get("notes"):
                raise HTTPException(409, "Approval requires a traceable source URL or note")
            if current.get("expires_at") and current["expires_at"] <= now:
                raise HTTPException(409, "Expired quotes cannot be approved")
        status = "approved" if data.approved else "candidate"
        row = repo.update(project_id, item_id, {
            "status": status,
            "updated_by": actor.user_id,
            "version": current["version"] + 1,
            "updated_at": now,
        })
        _snapshot(repo, row, "approved" if data.approved else "unapproved", actor.user_id, now)
        return _with_quote_state(row)


@router.delete("/{item_id}", status_code=204)
def archive_material_item(project_id: str, item_id: str, request: Request, actor=Depends(require("designs:write"))):
    now = int(time())
    with request.app.state.services.store.transaction(write=True) as db:
        _owned_project(db, project_id, actor)
        repo = _repository(db)
        current = repo.get(project_id, item_id)
        if not current:
            raise HTTPException(404, "Material catalog item not found")
        if current["status"] != "archived":
            row = repo.update(project_id, item_id, {
                "status": "archived",
                "updated_by": actor.user_id,
                "version": current["version"] + 1,
                "updated_at": now,
            })
            _snapshot(repo, row, "archived", actor.user_id, now)
    return None


@router.get("/{item_id}/versions")
def material_item_versions(project_id: str, item_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        _owned_project(db, project_id, actor)
        repo = _repository(db)
        if not repo.get(project_id, item_id):
            raise HTTPException(404, "Material catalog item not found")
        return {"versions": repo.versions(project_id, item_id)}
