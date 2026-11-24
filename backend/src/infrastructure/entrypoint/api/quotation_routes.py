"""Project quotation drafts with grouped line items and deterministic totals."""

from decimal import Decimal, ROUND_HALF_UP
from time import time
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.infrastructure.persistence.quotation_repository import QuotationRepository, QuotationTemplateRepository
from src.infrastructure.security.middleware import require


router = APIRouter(prefix="/api/v1/projects/{project_id}/quotations", tags=["quotations"])
template_router = APIRouter(prefix="/api/v1/quotation-templates", tags=["quotations"])


class QuoteLine(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=80)
    catalog_item_id: str | None = Field(default=None, max_length=36)
    name: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=2000)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    unit: str = Field(min_length=1, max_length=40)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    markup_percent: Decimal = Field(default=Decimal("0"), ge=0, le=1000, max_digits=8, decimal_places=3)
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=8, decimal_places=3)
    tax_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=8, decimal_places=3)
    transport_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    supplier: str | None = Field(default=None, max_length=240)
    source_name: str | None = Field(default=None, max_length=240)
    source_url: str | None = Field(default=None, max_length=2000)
    source_note: str | None = Field(default=None, max_length=2000)
    catalog_version: int | None = Field(default=None, ge=1)

    @field_validator("source_url")
    @classmethod
    def valid_source(cls, value):
        if value:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("source_url must be an http(s) URL")
        return value

    @model_validator(mode="after")
    def sourced_price(self):
        if self.unit_cost is not None and self.unit_cost > 0 and not (self.supplier and (self.source_url or self.source_note)):
            raise ValueError("a priced line requires supplier and a traceable source URL or note")
        return self


class QuoteGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    items: list[QuoteLine] = Field(default_factory=list, max_length=200)


class QuoteBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=80)
    kind: Literal["text", "table", "description"]
    title: str = Field(default="", max_length=160)
    content: str = Field(default="", max_length=10000)
    columns: list[str] = Field(default_factory=list, max_length=12)
    rows: list[list[str]] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def valid_table_shape(self):
        if self.kind == "table":
            if not self.columns or any(len(row) != len(self.columns) for row in self.rows):
                raise ValueError("table blocks require columns and rows with matching width")
            if any(not isinstance(cell, str) or len(cell) > 2000 for row in self.rows for cell in row):
                raise ValueError("table cells must be text up to 2000 characters")
        elif self.columns or self.rows:
            raise ValueError("columns and rows are only valid for table blocks")
        return self


class QuotationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=240)
    valid_until: int | None = Field(default=None, ge=0)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    groups: list[QuoteGroup] = Field(default_factory=list, max_length=80)
    narrative_blocks: list[QuoteBlock] = Field(default_factory=list, max_length=80)
    global_transport: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    conditions: str = Field(default="", max_length=5000)
    seller_contact: dict = Field(default_factory=dict)
    show_fields: dict[str, bool] = Field(default_factory=dict)
    source_artifact_id: str | None = Field(default=None, max_length=36)
    source_artifact_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def artifact_source_pair(self):
        if (self.source_artifact_id is None) != (self.source_artifact_version is None):
            raise ValueError("source_artifact_id and source_artifact_version must be provided together")
        return self


class QuotationTemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=160)
    content: QuotationInput


def _ownership(db, project_id, actor):
    project = db.one("projects", id=project_id)
    if not project or (not actor.privileged and project["owner_id"] != actor.user_id):
        raise HTTPException(404, "Project not found")


def _calculate(groups, currency, global_transport):
    cost = sales = discount = taxes = line_transport = Decimal("0")
    priced = unpriced = 0
    priced_lines = []
    for group in groups:
        for line in group["items"]:
            if line["unit_cost"] is None:
                unpriced += 1
                priced_lines.append({**line, "group_id": group["id"], "line_total": None})
                continue
            quantity = Decimal(str(line["quantity"]))
            base = Decimal(str(line["unit_cost"])) * quantity
            marked = base * (1 + Decimal(str(line["markup_percent"])) / 100)
            discount_amount = marked * Decimal(str(line["discount_percent"])) / 100
            taxable = marked - discount_amount
            tax_amount = taxable * Decimal(str(line["tax_percent"])) / 100
            transport = Decimal(str(line["transport_amount"]))
            total = taxable + tax_amount + transport
            cost += base
            sales += marked
            discount += discount_amount
            taxes += tax_amount
            line_transport += transport
            priced += 1
            priced_lines.append({**line, "group_id": group["id"], "base_cost": str(base), "sale_before_discount": str(marked),
                "discount_amount": str(discount_amount), "tax_amount": str(tax_amount), "line_total": str(total)})
    global_transport = Decimal(str(global_transport))
    margin = sales - cost - discount
    total = sales - discount + taxes + line_transport + global_transport
    quantum = Decimal("0.01")
    money = lambda amount: str(amount.quantize(quantum, rounding=ROUND_HALF_UP))
    return {"currency": currency, "line_count": priced + unpriced, "priced_line_count": priced, "unpriced_line_count": unpriced,
        "base_cost": money(cost), "sales_before_discount": money(sales), "discounts": money(discount), "margin": money(margin),
        "taxes": money(taxes), "line_transport": money(line_transport), "global_transport": money(global_transport),
        "grand_total": money(total) if not unpriced else None, "lines": priced_lines,
        "complete": unpriced == 0 and priced > 0}


def _snapshot(repo, row, actor_id, now):
    repo.add_version({"id": uuid4().hex, "quotation_id": row["id"], "project_id": row["project_id"],
        "version": row["version"], "snapshot": row, "created_by": actor_id, "created_at": now})


@router.get("")
def list_quotations(project_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        _ownership(db, project_id, actor)
        return {"items": QuotationRepository(db.connection).list(project_id)}


@router.post("", status_code=201)
def create_quotation(project_id: str, data: QuotationInput, request: Request,
                     actor=Depends(require("designs:write"))):
    now = int(time())
    payload = data.model_dump(mode="json")
    totals = _calculate(payload["groups"], data.currency, data.global_transport)
    quotation_id = str(uuid4())
    number = f"COT-{now}-{quotation_id[:6].upper()}"
    with request.app.state.services.store.transaction(write=True) as db:
        _ownership(db, project_id, actor)
        repo = QuotationRepository(db.connection)
        row = repo.insert({"id": quotation_id, "project_id": project_id, "created_by": actor.user_id,
            "number": number, "title": data.title, "status": "draft", "version": 1,
            "valid_until": data.valid_until, "currency": data.currency, "content": payload,
            "totals": totals, "created_at": now, "updated_at": now})
        _snapshot(repo, row, actor.user_id, now)
        return row


@router.get("/{quotation_id}")
def get_quotation(project_id: str, quotation_id: str, request: Request,
                  actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        _ownership(db, project_id, actor)
        row = QuotationRepository(db.connection).get(project_id, quotation_id)
        if not row:
            raise HTTPException(404, "Quotation not found")
        return row


@router.put("/{quotation_id}")
def update_quotation(project_id: str, quotation_id: str, data: QuotationInput, request: Request,
                     actor=Depends(require("designs:write"))):
    now = int(time())
    payload = data.model_dump(mode="json")
    totals = _calculate(payload["groups"], data.currency, data.global_transport)
    with request.app.state.services.store.transaction(write=True) as db:
        _ownership(db, project_id, actor)
        repo = QuotationRepository(db.connection)
        current = repo.get(project_id, quotation_id)
        if not current:
            raise HTTPException(404, "Quotation not found")
        if current["status"] != "draft":
            raise HTTPException(409, "Only draft quotations can be edited")
        row = repo.update(project_id, quotation_id, {"title": data.title, "valid_until": data.valid_until,
            "currency": data.currency, "content": payload, "totals": totals,
            "version": current["version"] + 1, "updated_at": now})
        _snapshot(repo, row, actor.user_id, now)
        return row


@router.post("/{quotation_id}/status")
def transition_quotation(project_id: str, quotation_id: str, data: dict, request: Request,
                         actor=Depends(require("designs:write"))):
    status = data.get("status") if isinstance(data, dict) else None
    allowed = {"draft": {"sent"}, "sent": {"accepted", "rejected", "expired"}, "accepted": set(), "rejected": set(), "expired": set()}
    now = int(time())
    with request.app.state.services.store.transaction(write=True) as db:
        _ownership(db, project_id, actor)
        repo = QuotationRepository(db.connection)
        current = repo.get(project_id, quotation_id)
        if not current:
            raise HTTPException(404, "Quotation not found")
        if status not in allowed.get(current["status"], set()):
            raise HTTPException(409, "Invalid quotation status transition")
        if status == "sent" and not current["totals"].get("complete"):
            raise HTTPException(409, "A quotation with unpriced lines cannot be sent")
        if status == "sent" and current.get("valid_until") is not None and current["valid_until"] < now:
            raise HTTPException(409, "An expired quotation cannot be sent")
        row = repo.update(project_id, quotation_id, {"status": status, "version": current["version"] + 1, "updated_at": now})
        _snapshot(repo, row, actor.user_id, now)
        return row


@router.get("/{quotation_id}/versions")
def quotation_history(project_id: str, quotation_id: str, request: Request,
                      actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        _ownership(db, project_id, actor)
        repo = QuotationRepository(db.connection)
        if not repo.get(project_id, quotation_id):
            raise HTTPException(404, "Quotation not found")
        return {"versions": repo.versions(project_id, quotation_id)}


@template_router.get("")
def list_quotation_templates(request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        return {"items": QuotationTemplateRepository(db.connection).list(actor.user_id)}


@template_router.post("", status_code=201)
def create_quotation_template(data: QuotationTemplateInput, request: Request,
                              actor=Depends(require("designs:write"))):
    now = int(time())
    with request.app.state.services.store.transaction(write=True) as db:
        repo = QuotationTemplateRepository(db.connection)
        if any(item["name"].casefold() == data.name.casefold() for item in repo.list(actor.user_id)):
            raise HTTPException(409, "A quotation template with this name already exists")
        content = data.content.model_dump(mode="json")
        # Templates preserve structure and wording; prices and source-specific catalog links must be revalidated.
        content["source_artifact_id"] = None
        content["source_artifact_version"] = None
        for group in content["groups"]:
            for line in group["items"]:
                line.update({"catalog_item_id": None, "catalog_version": None, "unit_cost": None,
                    "supplier": None, "source_name": None, "source_url": None, "source_note": None})
        return repo.insert({"id": str(uuid4()), "owner_id": actor.user_id, "name": data.name,
            "content": content, "created_at": now, "updated_at": now})


@template_router.delete("/{template_id}", status_code=204)
def delete_quotation_template(template_id: str, request: Request,
                              actor=Depends(require("designs:write"))):
    with request.app.state.services.store.transaction(write=True) as db:
        if not QuotationTemplateRepository(db.connection).delete(actor.user_id, template_id):
            raise HTTPException(404, "Quotation template not found")
    return None
